import { createApp } from 'vue'
import { ElButton } from 'element-plus/es/components/button/index.mjs'
import { ElCheckbox } from 'element-plus/es/components/checkbox/index.mjs'
import { ElConfigProvider } from 'element-plus/es/components/config-provider/index.mjs'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index.mjs'
import { ElIcon } from 'element-plus/es/components/icon/index.mjs'
import { ElInput } from 'element-plus/es/components/input/index.mjs'
import { ElInputNumber } from 'element-plus/es/components/input-number/index.mjs'
import { ElProgress } from 'element-plus/es/components/progress/index.mjs'
import { ElRadioButton, ElRadioGroup } from 'element-plus/es/components/radio/index.mjs'
import { ElOption, ElSelect } from 'element-plus/es/components/select/index.mjs'
import { ElTable, ElTableColumn } from 'element-plus/es/components/table/index.mjs'
import { ElTag } from 'element-plus/es/components/tag/index.mjs'
import { ElTooltip } from 'element-plus/es/components/tooltip/index.mjs'
import { ElUpload } from 'element-plus/es/components/upload/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/es/components/button/style/css.mjs'
import 'element-plus/es/components/checkbox/style/css.mjs'
import 'element-plus/es/components/config-provider/style/css.mjs'
import 'element-plus/es/components/form/style/css.mjs'
import 'element-plus/es/components/form-item/style/css.mjs'
import 'element-plus/es/components/icon/style/css.mjs'
import 'element-plus/es/components/input/style/css.mjs'
import 'element-plus/es/components/input-number/style/css.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import 'element-plus/es/components/option/style/css.mjs'
import 'element-plus/es/components/progress/style/css.mjs'
import 'element-plus/es/components/radio-button/style/css.mjs'
import 'element-plus/es/components/radio-group/style/css.mjs'
import 'element-plus/es/components/select/style/css.mjs'
import 'element-plus/es/components/table/style/css.mjs'
import 'element-plus/es/components/table-column/style/css.mjs'
import 'element-plus/es/components/tag/style/css.mjs'
import 'element-plus/es/components/tooltip/style/css.mjs'
import 'element-plus/es/components/upload/style/css.mjs'
import App from './App.vue'
import './styles.css'

const app = createApp(App)

const components = [
  ElButton,
  ElCheckbox,
  ElConfigProvider,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElOption,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTooltip,
  ElUpload
]

for (const component of components) {
  app.use(component)
}

app.mount('#app')
