import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { mountIconAnim } from './iconAnim'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import './styles/main.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

mountIconAnim()
