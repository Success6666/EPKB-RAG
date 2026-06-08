import base64
import hashlib
import logging
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from langchain_core.documents import Document

from app.core.config import Settings
from app.langchain_modules.model_io.generation import normalize_provider
from app.schemas.documents import DocumentIngestJob

logger = logging.getLogger(__name__)


class DocumentChunk(dict):
    """Dictionary-backed chunk to keep vector-store serialization simple."""


@dataclass(frozen=True)
class OcrText:
    raw_text: str
    clean_text: str
    llm_refined: bool
    avg_confidence: float | None = None
    min_confidence_seen: float | None = None
    recognition_mode: str = "ocr"
    ocr_text: str = ""
    vision_text: str = ""
    vision_model: str | None = None
    vision_used: bool = False
    line_count: int = 0
    low_confidence: bool = False
    complex_layout: bool = False


@dataclass(frozen=True)
class TextSection:
    text: str
    title: str = ""
    path: str = ""
    level: int = 0


class DocumentProcessor:
    def __init__(self, settings: Settings) -> None:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        self.settings = settings
        self._ocr_engine = None
        self._ocr_llm_available: bool | None = None
        separators = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
        separators = [
            "\n\n",
            "\n# ",
            "\n## ",
            "\n### ",
            "\n|",
            "\n- ",
            "\n* ",
            "\n",
            "\u3002",
            "\uff1b",
            "\uff01",
            "\uff1f",
            ".",
            "!",
            "?",
            "\uff0c",
            ",",
            " ",
            "",
        ]
        self.parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.parent_chunk_size,
            chunk_overlap=settings.parent_chunk_overlap,
            separators=separators,
        )
        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.child_chunk_size,
            chunk_overlap=settings.child_chunk_overlap,
            separators=separators,
        )

    def process(self, job: DocumentIngestJob) -> list[DocumentChunk]:
        doc_id = job.doc_id or uuid5(NAMESPACE_URL, f"{job.tenant_id}:{job.kb_id}:{job.file_path}:{job.source_uri}").hex
        documents = self._load_documents(job)
        normalized_documents = [
            Document(page_content=cleaned, metadata={**document.metadata})
            for document in documents
            if (cleaned := self._clean_text(document.page_content))
        ]

        chunks: list[DocumentChunk] = []
        section_documents = self._split_sections(normalized_documents)
        parent_splits = self.parent_splitter.split_documents(section_documents)
        for parent_index, parent in enumerate(parent_splits):
            parent_text = parent.page_content
            parent_id = uuid5(NAMESPACE_URL, f"{job.tenant_id}:{job.kb_id}:{doc_id}:parent:{parent_index}:{parent_text[:80]}").hex
            chunks.append(
                DocumentChunk(
                    id=parent_id,
                    text=parent_text,
                    metadata=self._metadata(job, doc_id, parent, parent_id, parent_index, "parent", parent_id, None),
                )
            )

            child_splits = self._semantic_child_splits(parent)
            for child_index, child in enumerate(child_splits):
                child_text = child.page_content
                child_id = uuid5(
                    NAMESPACE_URL,
                    f"{job.tenant_id}:{job.kb_id}:{doc_id}:child:{parent_index}:{child_index}:{child_text[:80]}",
                ).hex
                chunks.append(
                    DocumentChunk(
                        id=child_id,
                        text=child_text,
                        metadata=self._metadata(job, doc_id, child, child_id, parent_index, "child", parent_id, child_index),
                    )
                )

        return chunks

    def _semantic_child_splits(self, parent: Document) -> list[Document]:
        texts = semantic_child_split_text(
            parent.page_content,
            max_chars=self.settings.child_chunk_size,
            overlap_chars=self.settings.child_chunk_overlap,
        )
        return [Document(page_content=text, metadata={**parent.metadata}) for text in texts]

    def _metadata(
        self,
        job: DocumentIngestJob,
        doc_id: str,
        document: Document,
        chunk_id: str,
        parent_index: int,
        chunk_type: str,
        parent_id: str,
        child_index: int | None,
    ) -> dict[str, Any]:
        metadata = {
            **document.metadata,
            **job.metadata,
            "tenant_id": job.tenant_id,
            "kb_id": job.kb_id,
            "doc_id": doc_id,
            "chunk_id": chunk_id,
            "chunk_type": chunk_type,
            "parent_id": parent_id,
            "parent_index": parent_index,
            "chunk_index": parent_index if child_index is None else parent_index * 10000 + child_index,
            "file_name": job.file_name or self._file_name(job),
            "source_uri": job.source_uri or job.file_path,
            "page": self._page_number(document.metadata),
        }
        if child_index is not None:
            metadata["child_index"] = child_index
            metadata.pop("ocr_raw_text", None)
            metadata.pop("ocr_raw_truncated", None)
            metadata.pop("ocr_engine_text", None)
            metadata.pop("ocr_vision_text", None)
        return metadata

    def _load_documents(self, job: DocumentIngestJob) -> list[Document]:
        if job.content is not None:
            return [Document(page_content=job.content, metadata={"source": job.source_uri or "inline"})]
        if not job.file_path:
            raise ValueError("filePath or content is required.")

        path = Path(job.file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document file not found: {path}")

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            from langchain_community.document_loaders import PyPDFLoader

            documents = PyPDFLoader(str(path)).load()
            return documents + self._load_pdf_ocr(path, documents)
        if suffix == ".doc":
            return self._load_doc(path)
        if suffix == ".docx":
            from langchain_community.document_loaders import Docx2txtLoader

            documents = Docx2txtLoader(str(path)).load()
            documents.extend(self._load_docx_image_ocr(path))
            return documents
        if suffix == ".csv":
            return self._load_csv(path)
        if suffix in {".xls", ".xlsx"}:
            return self._load_excel(path)
        from langchain_community.document_loaders import TextLoader

        return TextLoader(str(path), encoding="utf-8", autodetect_encoding=True).load()

    def _load_doc(self, path: Path) -> list[Document]:
        for command in self._doc_extract_commands(path):
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired as exc:
                logger.warning("DOC extraction timed out for %s command=%s", path, command[0])
                continue
            if result.returncode != 0:
                logger.warning(
                    "DOC extraction failed for %s command=%s exit=%s stderr=%s",
                    path,
                    command[0],
                    result.returncode,
                    (result.stderr or "").strip()[:500],
                )
                continue
            text = self._clean_text(result.stdout or "")
            if text:
                return [Document(page_content=text, metadata={"source": str(path), "source_type": "doc"})]
        raise ValueError("Unable to read .doc file. Install antiword or catdoc in the FastAPI image.")

    def _doc_extract_commands(self, path: Path) -> list[list[str]]:
        commands: list[list[str]] = []
        if shutil.which("antiword"):
            commands.append(["antiword", "-m", "UTF-8.txt", str(path)])
            commands.append(["antiword", str(path)])
        if shutil.which("catdoc"):
            commands.append(["catdoc", "-w", str(path)])
            commands.append(["catdoc", str(path)])
        return commands

    def _load_docx_image_ocr(self, path: Path) -> list[Document]:
        if not self.settings.ocr_enabled or not zipfile.is_zipfile(path):
            return []
        documents: list[Document] = []
        try:
            with zipfile.ZipFile(path) as archive:
                image_names = [
                    name for name in archive.namelist()
                    if name.startswith("word/media/") and self._is_supported_image(name)
                ]
                for index, name in enumerate(image_names[: self.settings.ocr_max_images_per_document], start=1):
                    ocr = self._ocr_image_bytes(archive.read(name), f"{path.name}:{name}")
                    if ocr is None or not ocr.clean_text:
                        continue
                    documents.append(
                        Document(
                            page_content=f"DOCX image OCR {index} ({Path(name).name}):\n{ocr.clean_text}",
                            metadata={
                                "source": str(path),
                                "source_type": "docx_image_ocr",
                                "image": Path(name).name,
                                "image_index": index,
                                **self._ocr_metadata(ocr),
                            },
                        )
                    )
        except Exception as exc:
            logger.warning("DOCX image OCR skipped for %s: %s", path, exc)
        return documents

    def _load_pdf_ocr(self, path: Path, text_documents: list[Document]) -> list[Document]:
        if not self.settings.ocr_enabled:
            return []
        text_chars_by_page = self._text_chars_by_page(text_documents)
        documents: list[Document] = []
        try:
            import fitz

            pdf = fitz.open(str(path))
            try:
                page_count = min(pdf.page_count, self.settings.ocr_pdf_max_pages)
                zoom = max(1.0, self.settings.ocr_render_dpi / 72)
                matrix = fitz.Matrix(zoom, zoom)
                for page_index in range(page_count):
                    page_number = page_index + 1
                    if text_chars_by_page.get(page_number, 0) >= self.settings.ocr_pdf_min_text_chars:
                        continue
                    pixmap = pdf.load_page(page_index).get_pixmap(matrix=matrix, alpha=False)
                    ocr = self._ocr_image_bytes(pixmap.tobytes("png"), f"{path.name}:page:{page_number}")
                    if ocr is None or not ocr.clean_text:
                        continue
                    documents.append(
                        Document(
                            page_content=f"PDF page OCR {page_number}:\n{ocr.clean_text}",
                            metadata={
                                "source": str(path),
                                "source_type": "pdf_page_ocr",
                                "page": page_index,
                                **self._ocr_metadata(ocr),
                            },
                        )
                    )
            finally:
                pdf.close()
        except Exception as exc:
            logger.warning("PDF OCR skipped for %s: %s", path, exc)
        return documents

    def _ocr_image_bytes(self, image_bytes: bytes, source_label: str) -> OcrText | None:
        if not image_bytes:
            return None
        try:
            from PIL import Image

            image = Image.open(BytesIO(image_bytes))
            return self._ocr_image(image, source_label)
        except Exception as exc:
            logger.warning("OCR image skipped for %s: %s", source_label, exc)
            return None

    def _ocr_image(self, image: Any, source_label: str) -> OcrText | None:
        rapid_ocr = self._rapid_ocr_image(image, source_label)
        strategy = self.settings.ocr_strategy.lower().strip()
        if strategy == "ocr_only":
            return rapid_ocr

        if not self._is_vision_model_available():
            return rapid_ocr

        vision_reason = self._vision_reason(rapid_ocr, strategy)
        if not vision_reason:
            return rapid_ocr

        vision_text = self._vision_image_to_text(image, source_label, vision_reason)
        if not vision_text:
            return rapid_ocr
        return self._combine_ocr_and_vision(rapid_ocr, vision_text, vision_reason)

    def _rapid_ocr_image(self, image: Any, source_label: str) -> OcrText | None:
        engine = self._get_ocr_engine()
        if engine is None:
            return None
        lines: list[str] = []
        scores: list[float] = []
        seen: set[str] = set()
        for variant in self._ocr_image_variants(image):
            try:
                import cv2
                import numpy as np

                image_array = cv2.cvtColor(np.array(variant.convert("RGB")), cv2.COLOR_RGB2BGR)
                raw_result = engine(image_array)
                for text, score in self._parse_ocr_result(raw_result):
                    cleaned = self._clean_text(text)
                    if not cleaned or score < self.settings.ocr_min_confidence:
                        continue
                    key = re.sub(r"\s+", "", cleaned).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    lines.append(cleaned)
                    scores.append(score)
            except Exception as exc:
                logger.warning("OCR variant failed for %s: %s", source_label, exc)
        raw_text = "\n".join(lines)
        if not raw_text:
            return None
        clean_text, llm_refined = self._refine_ocr_text(raw_text, source_label)
        return OcrText(
            raw_text=normalize_ocr_text(raw_text),
            clean_text=clean_text,
            llm_refined=llm_refined,
            avg_confidence=sum(scores) / len(scores) if scores else None,
            min_confidence_seen=min(scores) if scores else None,
            recognition_mode="ocr",
            ocr_text=normalize_ocr_text(raw_text),
            line_count=len(lines),
            low_confidence=self._is_low_confidence(scores),
            complex_layout=len(lines) >= self.settings.ocr_complex_layout_min_lines,
        )

    def _vision_reason(self, ocr: OcrText | None, strategy: str) -> str:
        if strategy in {"vision", "vision_first"}:
            return "vision_first"
        if strategy == "hybrid":
            return "hybrid"
        if strategy != "auto":
            return ""
        if ocr is None or not ocr.clean_text:
            return "no_ocr_text"
        if ocr.low_confidence:
            return "low_confidence"
        if ocr.complex_layout:
            return "complex_layout"
        return ""

    def _combine_ocr_and_vision(self, ocr: OcrText | None, vision_text: str, reason: str) -> OcrText:
        vision_clean = normalize_ocr_text(vision_text)[: self.settings.ocr_vision_max_chars]
        vision_model = self._vision_model_name()
        if ocr is None:
            return OcrText(
                raw_text=vision_clean,
                clean_text=vision_clean,
                llm_refined=False,
                recognition_mode="vision",
                vision_text=vision_clean,
                vision_model=vision_model,
                vision_used=True,
                low_confidence=True,
            )

        if reason in {"hybrid", "complex_layout"}:
            clean_text = join_unique_texts([ocr.clean_text, vision_clean])
            mode = "hybrid"
        elif reason == "vision_first":
            clean_text = vision_clean or ocr.clean_text
            mode = "vision_first"
        else:
            clean_text = vision_clean or ocr.clean_text
            mode = "vision_fallback"

        return OcrText(
            raw_text=ocr.raw_text,
            clean_text=clean_text,
            llm_refined=ocr.llm_refined,
            avg_confidence=ocr.avg_confidence,
            min_confidence_seen=ocr.min_confidence_seen,
            recognition_mode=mode,
            ocr_text=ocr.ocr_text or ocr.raw_text,
            vision_text=vision_clean,
            vision_model=vision_model,
            vision_used=True,
            line_count=ocr.line_count,
            low_confidence=ocr.low_confidence,
            complex_layout=ocr.complex_layout,
        )

    def _is_low_confidence(self, scores: list[float]) -> bool:
        if not scores:
            return True
        return (sum(scores) / len(scores)) < self.settings.ocr_low_confidence_threshold

    def _is_vision_model_available(self) -> bool:
        model = self._vision_model_name()
        if not model:
            return False
        if self.settings.ocr_vision_model:
            return True
        return any(keyword and keyword in model.lower() for keyword in self._vision_model_keywords())

    def _vision_model_name(self) -> str:
        return (self.settings.ocr_vision_model or self.settings.ollama_generation_model or "").strip()

    def _vision_model_keywords(self) -> list[str]:
        return [keyword.strip().lower() for keyword in self.settings.ocr_vision_model_keywords.split(",")]

    def _vision_image_to_text(self, image: Any, source_label: str, reason: str) -> str:
        model = self._vision_model_name()
        if not model:
            return ""
        try:
            import httpx

            image_bytes = self._image_to_png_bytes(self._resize_for_vision(image))
            payload = {
                "model": model,
                "prompt": self._vision_ocr_prompt(source_label, reason),
                "images": [base64.b64encode(image_bytes).decode("ascii")],
                "stream": False,
                "options": {"temperature": 0.0},
            }
            timeout = httpx.Timeout(self.settings.ocr_vision_timeout_seconds, connect=3.0)
            with httpx.Client(timeout=timeout) as client:
                response = client.post(f"{self.settings.ollama_base_url.rstrip('/')}/api/generate", json=payload)
                response.raise_for_status()
                return normalize_ocr_text(str(response.json().get("response") or ""))
        except Exception as exc:
            logger.warning("Vision OCR skipped for %s reason=%s model=%s: %s", source_label, reason, model, exc)
            return ""

    def _vision_ocr_prompt(self, source_label: str, reason: str) -> str:
        return (
            "You are transcribing text from an image for a RAG knowledge base.\n"
            "Only transcribe visible text. Do not summarize, rewrite, infer, or add missing facts.\n"
            "Preserve all readable words, numbers, dates, names, model numbers, amounts, units, labels and codes.\n"
            "Keep tables, lists and reading order as faithfully as possible.\n"
            "If handwriting or a token is unclear, keep the closest visible form and mark it as [unclear].\n"
            "Return only the complete transcription text, with no explanation.\n\n"
            f"OCR source: {source_label}\n"
            f"Vision fallback reason: {reason}\n"
        )

    def _resize_for_vision(self, image: Any) -> Any:
        from PIL import ImageOps

        normalized = ImageOps.exif_transpose(image).convert("RGB")
        width, height = normalized.size
        max_side = max(width, height)
        if max_side <= self.settings.ocr_vision_max_image_side:
            return normalized
        scale = self.settings.ocr_vision_max_image_side / max_side
        from PIL import Image

        return normalized.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

    def _image_to_png_bytes(self, image: Any) -> bytes:
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _get_ocr_engine(self):
        if self._ocr_engine is not None:
            return self._ocr_engine
        try:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr_engine = RapidOCR()
        except Exception as exc:
            logger.warning("OCR engine is unavailable: %s", exc)
            self._ocr_engine = False
        return None if self._ocr_engine is False else self._ocr_engine

    def _ocr_image_variants(self, image: Any) -> list[Any]:
        from PIL import ImageEnhance, ImageOps, ImageStat

        normalized = ImageOps.exif_transpose(image).convert("RGB")
        normalized = self._resize_for_ocr(normalized)
        luminance = ImageStat.Stat(normalized.convert("L")).mean[0]
        brightness = 1.25 if luminance < 95 else 1.0
        enhanced = ImageEnhance.Brightness(normalized).enhance(brightness)
        enhanced = ImageOps.autocontrast(enhanced, cutoff=1)
        enhanced = ImageEnhance.Contrast(enhanced).enhance(1.45)
        enhanced = ImageEnhance.Sharpness(enhanced).enhance(1.35)

        variants = [enhanced]
        try:
            import cv2
            import numpy as np
            from PIL import Image

            gray = cv2.cvtColor(np.array(enhanced), cv2.COLOR_RGB2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
            threshold = cv2.adaptiveThreshold(
                clahe,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                11,
            )
            variants.append(Image.fromarray(threshold).convert("RGB"))
        except Exception as exc:
            logger.warning("OCR threshold preprocessing skipped: %s", exc)
        return variants

    def _resize_for_ocr(self, image: Any) -> Any:
        width, height = image.size
        max_side = max(width, height)
        min_side = min(width, height)
        if max_side <= 0 or min_side <= 0:
            return image
        scale = 1.0
        if max_side < self.settings.ocr_min_image_side:
            scale = self.settings.ocr_min_image_side / max_side
        if max_side * scale > self.settings.ocr_max_image_side:
            scale = self.settings.ocr_max_image_side / max_side
        if scale <= 1.05:
            return image
        from PIL import Image

        return image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

    def _parse_ocr_result(self, raw_result: Any) -> list[tuple[str, float]]:
        result = raw_result[0] if isinstance(raw_result, tuple) else raw_result
        parsed: list[tuple[str, float]] = []
        for item in result or []:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            text = str(item[1] or "").strip()
            try:
                score = float(item[2])
            except (TypeError, ValueError):
                score = 1.0
            parsed.append((text, score))
        return parsed

    def _refine_ocr_text(self, text: str, source_label: str) -> tuple[str, bool]:
        cleaned = normalize_ocr_text(text)
        if (
            not cleaned
            or not self.settings.ocr_llm_refinement_enabled
            or len(cleaned) < self.settings.ocr_llm_refinement_min_chars
            or self._ocr_llm_available is False
        ):
            return cleaned, False
        prompt_text = cleaned[: self.settings.ocr_llm_refinement_max_chars]
        prompt = (
            "You are an OCR text formatting assistant, not a summarization assistant.\n"
            "Only organize layout. Do not rewrite meaning, summarize, delete readable content, or add facts.\n"
            "Preserve all readable words, numbers, dates, names, model numbers, amounts, units, labels and codes.\n"
            "You may only fix broken line breaks, spacing, paragraph boundaries, headings, lists and table order.\n"
            "If text is uncertain, keep the original token and mark it as [unclear] instead of guessing.\n"
            "Return the complete cleaned text only, with no explanation.\n\n"
            f"OCR source: {source_label}\n\n"
            f"Raw OCR text:\n{prompt_text}\n\n"
            "Cleaned OCR text:"
        )
        try:
            import httpx

            provider = normalize_provider(self.settings.generation_provider)
            timeout = httpx.Timeout(self.settings.ocr_llm_refinement_timeout_seconds, connect=2.0)
            if provider == "ollama":
                payload = {
                    "model": self._default_generation_model("ollama"),
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0},
                }
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(f"{self.settings.ollama_base_url.rstrip('/')}/api/generate", json=payload)
                    response.raise_for_status()
                    refined = normalize_ocr_text(str(response.json().get("response") or ""))
            else:
                route = self._openai_compatible_generation_route(provider)
                if not route["api_key"]:
                    logger.warning("OCR LLM refinement skipped for %s: missing API key for provider=%s", source_label, provider)
                    self._ocr_llm_available = False
                    return cleaned, False
                payload = {
                    "model": route["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "temperature": 0.0,
                }
                headers = {"Authorization": f"Bearer {route['api_key']}"}
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(f"{route['base_url']}/chat/completions", json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                refined = normalize_ocr_text(str(message.get("content") or choice.get("text") or ""))
            self._ocr_llm_available = True
            return refined or cleaned, bool(refined)
        except Exception as exc:
            self._ocr_llm_available = False
            logger.warning("OCR LLM refinement skipped for %s: %s", source_label, exc)
            return cleaned, False

    def _openai_compatible_generation_route(self, provider: str) -> dict[str, str | None]:
        if provider == "deepseek":
            return {
                "base_url": self.settings.deepseek_base_url.rstrip("/"),
                "model": self._default_generation_model("deepseek"),
                "api_key": self.settings.deepseek_api_key or self.settings.openai_compatible_api_key,
            }
        if provider == "dashscope":
            return {
                "base_url": self.settings.dashscope_base_url.rstrip("/"),
                "model": self._default_generation_model("dashscope"),
                "api_key": self.settings.dashscope_api_key or self.settings.openai_compatible_api_key,
            }
        return {
            "base_url": (self.settings.openai_compatible_base_url or self.settings.openai_base_url).rstrip("/"),
            "model": self._default_generation_model("openai-compatible"),
            "api_key": self.settings.openai_compatible_api_key or self.settings.openai_api_key,
        }

    def _default_generation_model(self, provider: str) -> str:
        configured_provider = normalize_provider(self.settings.generation_provider)
        if self.settings.default_chat_model and configured_provider == provider:
            return self.settings.default_chat_model
        if provider == "ollama":
            return self.settings.ollama_generation_model
        if provider == "deepseek":
            return "deepseek-v4-pro"
        if provider == "dashscope":
            return "qwen-plus"
        return self.settings.openai_model

    def _ocr_metadata(self, ocr: OcrText) -> dict[str, Any]:
        raw_text = ocr.raw_text
        clean_text = ocr.clean_text
        raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest() if raw_text else ""
        raw_max_chars = max(0, self.settings.ocr_metadata_raw_max_chars)
        metadata: dict[str, Any] = {
            "ocr_cleaned": True,
            "ocr_llm_refined": ocr.llm_refined,
            "ocr_recognition_mode": ocr.recognition_mode,
            "ocr_vision_used": ocr.vision_used,
            "ocr_raw_hash": raw_hash,
            "ocr_raw_chars": len(raw_text),
            "ocr_clean_chars": len(clean_text),
            "ocr_line_count": ocr.line_count,
            "ocr_low_confidence": ocr.low_confidence,
            "ocr_complex_layout": ocr.complex_layout,
        }
        if raw_text:
            metadata["ocr_raw_text"] = raw_text[:raw_max_chars]
            metadata["ocr_raw_truncated"] = len(raw_text) > raw_max_chars
        if ocr.ocr_text:
            metadata["ocr_engine_text"] = ocr.ocr_text[:raw_max_chars]
            metadata["ocr_engine_hash"] = hashlib.sha256(ocr.ocr_text.encode("utf-8")).hexdigest()
        if ocr.vision_text:
            metadata["ocr_vision_text"] = ocr.vision_text[:raw_max_chars]
            metadata["ocr_vision_hash"] = hashlib.sha256(ocr.vision_text.encode("utf-8")).hexdigest()
        if ocr.vision_model:
            metadata["ocr_vision_model"] = ocr.vision_model
        if ocr.avg_confidence is not None:
            metadata["ocr_avg_confidence"] = round(ocr.avg_confidence, 4)
        if ocr.min_confidence_seen is not None:
            metadata["ocr_min_confidence_seen"] = round(ocr.min_confidence_seen, 4)
        return metadata

    def _text_chars_by_page(self, documents: list[Document]) -> dict[int, int]:
        counts: dict[int, int] = {}
        for document in documents:
            page = self._page_number(document.metadata)
            if page is None:
                continue
            counts[page] = counts.get(page, 0) + len(re.sub(r"\s+", "", document.page_content or ""))
        return counts

    def _is_supported_image(self, name: str) -> bool:
        return Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

    def _split_sections(self, documents: list[Document]) -> list[Document]:
        sections: list[Document] = []
        for document in documents:
            parts = split_by_headings(document.page_content)
            if len(parts) <= 1:
                sections.append(document)
                continue
            for section_index, part in enumerate(parts):
                sections.append(
                    Document(
                        page_content=part.text,
                        metadata={
                            **document.metadata,
                            "section_index": section_index,
                            "section_title": part.title or first_line(part.text),
                            "section_path": part.path or part.title,
                            "section_level": part.level,
                        },
                    )
                )
        return sections

    def _load_csv(self, path: Path) -> list[Document]:
        import pandas as pd

        read_kwargs: dict[str, Any] = {"dtype": object, "keep_default_na": True}
        try:
            dataframe = pd.read_csv(path, encoding="utf-8-sig", **read_kwargs)
        except UnicodeDecodeError:
            dataframe = pd.read_csv(path, encoding="gb18030", **read_kwargs)
        return self._dataframe_to_documents(dataframe, str(path))

    def _load_excel(self, path: Path) -> list[Document]:
        import pandas as pd

        sheets = pd.read_excel(path, sheet_name=None, dtype=object)
        documents: list[Document] = []
        for sheet_name, dataframe in sheets.items():
            documents.extend(self._dataframe_to_documents(dataframe, str(path), str(sheet_name)))
        return documents

    def _dataframe_to_documents(self, dataframe: Any, source: str, sheet_name: str | None = None) -> list[Document]:
        dataframe = self._clean_dataframe(dataframe)
        documents: list[Document] = []
        for row_number, row in enumerate(dataframe.to_dict(orient="records"), start=1):
            pairs = [(str(column), str(value).strip()) for column, value in row.items() if str(value).strip()]
            if not pairs:
                continue
            content = "\n".join(f"{column}: {value}" for column, value in pairs)
            metadata = {"source": source, "row": row_number}
            if sheet_name:
                metadata["sheet"] = sheet_name
            documents.append(Document(page_content=content, metadata=metadata))
        return documents

    def _clean_dataframe(self, dataframe: Any) -> Any:
        import numpy as np
        import pandas as pd

        cleaned = dataframe.copy()
        cleaned = cleaned.replace([np.inf, -np.inf], pd.NA)
        cleaned = cleaned.replace(r"^\s*$", pd.NA, regex=True)
        cleaned = cleaned.dropna(axis=0, how="all").dropna(axis=1, how="all")
        cleaned.columns = self._normalize_columns(cleaned.columns)
        cleaned = cleaned.fillna("")
        cell_mapper = cleaned.map if hasattr(cleaned, "map") else cleaned.applymap
        cleaned = cell_mapper(self._clean_cell)
        cleaned = cleaned.loc[cleaned.astype(str).agg("".join, axis=1).str.strip() != ""]
        return cleaned

    def _normalize_columns(self, columns: Any) -> list[str]:
        seen: dict[str, int] = {}
        normalized: list[str] = []
        for index, column in enumerate(columns, start=1):
            name = str(column).strip()
            if not name or name.lower() in {"nan", "none", "unnamed: 0"}:
                name = f"column_{index}"
            count = seen.get(name, 0)
            seen[name] = count + 1
            normalized.append(name if count == 0 else f"{name}_{count + 1}")
        return normalized

    def _clean_cell(self, value: Any) -> str:
        import math
        import pandas as pd

        if value is None or pd.isna(value):
            return ""
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        text = self._clean_text(str(value))
        return text[:2000] if len(text) > 2000 else text

    def _clean_text(self, text: str) -> str:
        text = text.replace("\u0000", " ")
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _file_name(self, job: DocumentIngestJob) -> str | None:
        if job.file_path:
            return Path(job.file_path).name
        return None

    def _page_number(self, metadata: dict) -> int | None:
        page = metadata.get("page")
        if isinstance(page, int):
            return page + 1
        return None


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")[:160]


HEADING_PATTERN = re.compile(
    r"(?m)^(?P<head>\s*(?:#{1,6}\s+|"
    r"\u7b2c[\u4e00-\u9fff0-9]+[\u7ae0\u8282\u7bc7\u90e8\u6761\u6b3e]\s*|"
    r"[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u4e07]+[\u3001.\uff0e]\s*|"
    r"[0-9]+(?:[.\uff0e][0-9]+)*[\u3001.\uff0e)\uff09\s]+).{1,160})$"
)


def split_by_headings(text: str) -> list[TextSection]:
    matches = [match for match in HEADING_PATTERN.finditer(text) if not is_table_separator(match.group("head"))]
    if not matches:
        return [TextSection(text=text)]

    sections: list[TextSection] = []
    if matches[0].start() > 0:
        intro = text[: matches[0].start()].strip()
        if intro:
            title = first_line(intro)
            sections.append(TextSection(text=intro, title=title, path=title, level=0))

    heading_stack: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        if not section:
            continue
        title = clean_heading(match.group("head"))
        level = heading_level(match.group("head"))
        heading_stack = [(item_level, item_title) for item_level, item_title in heading_stack if item_level < level]
        heading_stack.append((level, title))
        sections.append(TextSection(text=section, title=title, path=" > ".join(item[1] for item in heading_stack), level=level))
    return sections or [TextSection(text=text)]


def heading_level(value: str) -> int:
    stripped = value.lstrip()
    if stripped.startswith("#"):
        return min(len(stripped) - len(stripped.lstrip("#")), 6)
    if re.match(r"\s*\u7b2c.+[\u7ae0\u7bc7\u90e8]", value):
        return 1
    if re.match(r"\s*\u7b2c.+\u8282", value):
        return 2
    if re.match(r"\s*\u7b2c.+[\u6761\u6b3e]", value):
        return 3
    return max(2, min(value.count(".") + value.count("\uff0e") + 1, 6))


def clean_heading(value: str) -> str:
    return re.sub(r"^\s*#{1,6}\s*", "", value).strip()[:160]


def is_table_separator(value: str) -> bool:
    return bool(re.fullmatch(r"\s*\|?[\s:|\-]+\|?\s*", value or ""))


def semantic_child_split_text(text: str, max_chars: int, overlap_chars: int = 0) -> list[str]:
    max_chars = max(int(max_chars or 0), 1)
    overlap_budget = min(max(int(overlap_chars or 0), 0), max_chars // 3)
    units = semantic_text_units(text, max_chars)
    chunks: list[str] = []
    current: list[str] = []

    for unit in units:
        if len(unit) > max_chars:
            flush_semantic_chunk(chunks, current)
            current = []
            chunks.extend(hard_split_text(unit, max_chars, overlap_budget))
            continue

        if current and semantic_join_length(current + [unit]) > max_chars:
            flush_semantic_chunk(chunks, current)
            current = trailing_overlap_units(current, overlap_budget)
            if current and semantic_join_length(current + [unit]) > max_chars:
                current = []
        current.append(unit)

    flush_semantic_chunk(chunks, current)
    return chunks


def semantic_text_units(text: str, max_chars: int) -> list[str]:
    normalized = re.sub(r"\r\n?", "\n", str(text or "")).strip()
    if not normalized:
        return []

    units: list[str] = []
    for paragraph in [part.strip() for part in re.split(r"\n\s*\n+", normalized) if part.strip()]:
        paragraph = normalize_semantic_paragraph(paragraph)
        if len(paragraph) <= max_chars:
            units.append(paragraph)
            continue
        units.extend(split_semantic_paragraph(paragraph, max_chars))
    return units


def normalize_semantic_paragraph(paragraph: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in paragraph.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    return "\n".join(lines)


def split_semantic_paragraph(paragraph: str, max_chars: int) -> list[str]:
    lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
    if len(lines) > 1:
        units = group_heading_lines(lines, max_chars)
        if all(len(unit) <= max_chars for unit in units):
            return units

    sentences = split_sentences(paragraph)
    units: list[str] = []
    for sentence in sentences:
        units.append(sentence)
    return units


def group_heading_lines(lines: list[str], max_chars: int) -> list[str]:
    units: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if is_heading_line(line) and index + 1 < len(lines):
            combined = f"{line}\n{lines[index + 1]}"
            if len(combined) <= max_chars:
                units.append(combined)
                index += 2
                continue
        units.append(line)
        index += 1
    return units


def is_heading_line(line: str) -> bool:
    return bool(HEADING_PATTERN.match(line.strip()))


def split_sentences(paragraph: str) -> list[str]:
    parts = re.split(r"([。！？；;.!?]+[\"')\]\}）】》”’]*\s*)", paragraph)
    sentences: list[str] = []
    current = ""
    for part in parts:
        if not part:
            continue
        current += part
        if re.fullmatch(r"[。！？；;.!?]+[\"')\]\}）】》”’]*\s*", part):
            sentence = current.strip()
            if sentence:
                sentences.append(sentence)
            current = ""
    tail = current.strip()
    if tail:
        sentences.append(tail)
    return sentences or [paragraph.strip()]


def hard_split_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    value = str(text or "").strip()
    while start < len(value):
        end = min(start + max_chars, len(value))
        if end < len(value):
            boundary = last_soft_boundary(value, start + max_chars // 2, end)
            if boundary > start:
                end = boundary
        chunk = value[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(value):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def last_soft_boundary(text: str, start: int, end: int) -> int:
    for index in range(end - 1, start - 1, -1):
        if text[index] in "\n 。！？；;,.!?，、":
            return index + 1
    return end


def flush_semantic_chunk(chunks: list[str], current: list[str]) -> None:
    if current:
        chunk = "\n\n".join(current).strip()
        if chunk:
            chunks.append(chunk)


def semantic_join_length(units: list[str]) -> int:
    if not units:
        return 0
    return sum(len(unit) for unit in units) + 2 * (len(units) - 1)


def trailing_overlap_units(units: list[str], overlap_chars: int) -> list[str]:
    if overlap_chars <= 0:
        return []
    selected: list[str] = []
    for unit in reversed(units):
        candidate = [unit, *selected]
        if semantic_join_length(candidate) > overlap_chars:
            break
        selected = candidate
    return selected


def normalize_ocr_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = re.sub(r"[ \t\r\f\v]+", " ", raw_line).strip()
        if not line:
            continue
        line = re.sub(r"\s+([,.;:!?\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f])", r"\1", line)
        line = re.sub(r"([\(\[\{\uff08\u3010\u300a])\s+", r"\1", line)
        line = re.sub(r"\s+([\)\]\}\uff09\u3011\u300b])", r"\1", line)
        line = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", line)
        lines.append(line)

    normalized: list[str] = []
    previous = ""
    for line in lines:
        key = re.sub(r"\s+", "", line).lower()
        if key and key == previous:
            continue
        normalized.append(line)
        previous = key
    return "\n".join(normalized).strip()


def join_unique_texts(texts: list[str]) -> str:
    joined: list[str] = []
    seen: set[str] = set()
    for text in texts:
        normalized = normalize_ocr_text(text)
        if not normalized:
            continue
        key = re.sub(r"\s+", "", normalized).lower()
        if key in seen:
            continue
        seen.add(key)
        joined.append(normalized)
    return "\n\n".join(joined).strip()
