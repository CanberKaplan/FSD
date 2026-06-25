self.addEventListener('fetch', (event) => {});
2.  **HTML'e Kayıt Kodunu Ekleme:** `public/index.html` dosyanızdaki `<script>` bloğunun en altına şu satırları ekleyin:
```javascript
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js')
    .then(() => console.log('Service Worker yüklendi.'));
}
3.  **Önemli:** Eğer telefonunuzdan test ediyorsanız, tarayıcınızın (Chrome veya Safari) **HTTPS** bağlantısı beklemesi çok olasıdır. `http://192.168.x.x` adresinde bazı PWA özellikleri (yükleme istemi gibi) güvenlik nedeniyle çalışmayabilir. Bu yüzden telefonunuzda "Ana Ekrana Ekle" seçeneğini manuel olarak tarayıcı menüsünden seçmeyi deneyin.