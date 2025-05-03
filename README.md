# Telegram Group Manager API

Bu proje, Telegram grupları oluşturmak, davet bağlantıları göndermek, gruplar içerisinde mesajlar göndermek ve grup mesajlarını dinlemek için bir REST API sunar. Telethon kütüphanesi kullanılarak geliştirilmiştir.

## Özellikler

- Telegram grupları oluşturma
- Gruplara davet bağlantıları oluşturma ve gönderme
- Belirli kullanıcılardan gönderilmiş gibi görünen mesajlar gönderme
- Birden fazla Telegram grubunu eş zamanlı dinleme
- Gruplarda gönderilen mesajları takip etme
- REST API aracılığıyla tüm işlemleri otomatikleştirme

## Kurulum

1. Gerekli kütüphaneleri yükleyin:
```bash
pip install -r requirements.txt
```

2. Telegram API kimlik bilgilerinizi almanız gerekiyor:
   - [https://my.telegram.org](https://my.telegram.org) adresine gidin
   - "API Development Tools" bölümüne giriş yapın
   - Bir uygulama oluşturun ve API_ID ve API_HASH bilgilerini alın

3. `.env` dosyasını düzenleyin:
   - `API_ID` değerini Telegram'dan aldığınız API ID ile değiştirin
   - `API_HASH` değerini Telegram'dan aldığınız API Hash ile değiştirin
   - `PHONE_NUMBER` değerini ülke kodu dahil telefon numaranızla değiştirin (örn. +905551112233)

## REST API Kullanımı

API'yi çalıştırmak için:

```bash
python telegram_api.py
```

API, varsayılan olarak `http://127.0.0.1:5000` adresinde çalışır ve şu endpoint'leri sunar:

### 1. Grup Oluşturma API

**Endpoint:** `/create-telegram-group`

**Method:** POST

**Body:**
```json
{
  "group_name": "Grup Adı",
  "group_description": "Grup Açıklaması",
  "phones": ["+905551112233", "+905551112244"],
  "invite_message": "Grubumuza davetlisiniz!"
}
```

**Cevap:**
```json
{
  "success": true,
  "group": {
    "name": "Grup Adı",
    "invite_link": "https://t.me/+abcdef123456"
  },
  "invitations": [
    {
      "phone": "+905551112233",
      "status": "success",
      "message": "Invitation sent successfully"
    }
  ]
}
```

### 2. Grup Mesajı Gönderme API

**Endpoint:** `/send-telegram-group-message`

**Method:** POST

**Body:**
```json
{
  "group_link": "https://t.me/+abcdef123456",
  "sender_name": "Ahmet Yılmaz",
  "sender_phone": "+905551112233",
  "message": "Merhaba, bu bir test mesajıdır!"
}
```

**Cevap:**
```json
{
  "success": true,
  "group_link": "https://t.me/+abcdef123456",
  "message": "Message sent successfully"
}
```

### 3. Grup Mesajlarını Dinleme API

**Endpoint:** `/listen-to-group`

**Method:** POST

**Body:**
```json
{
  "group_links": [
    "https://t.me/+abcdef123456",
    "https://t.me/ikincigrup"
  ]
}
```

**Alternatif (Tek Grup İçin):**
```json
{
  "group_link": "https://t.me/+abcdef123456"
}
```

**Cevap:**
```json
{
  "success": true,
  "groups": [
    {
      "id": 1234567890,
      "title": "Grup Adı",
      "link": "https://t.me/+abcdef123456"
    },
    {
      "id": 1234567891,
      "title": "İkinci Grup",
      "link": "https://t.me/ikincigrup"
    }
  ],
  "errors": [],
  "message": "Now listening to 2 group(s)"
}
```

### 4. Grup Mesajlarını Alma API

**Endpoint:** `/get-group-messages`

**Method:** POST

**Body:**
```json
{
  "group_link": "https://t.me/+abcdef123456"
}
```

**Cevap:**
```json
{
  "success": true,
  "group": {
    "id": 1234567890,
    "title": "Grup Adı",
    "link": "https://t.me/+abcdef123456"
  },
  "messages": [
    {
      "id": 1001,
      "text": "Merhaba, nasılsınız?",
      "date": "2025-04-05T14:30:45",
      "sender": {
        "id": 123456789,
        "first_name": "Mehmet",
        "last_name": "Yılmaz",
        "username": "mehmet_yilmaz",
        "phone": null
      }
    }
  ]
}
```

### 5. Grup Dinlemeyi Durdurma API

**Endpoint:** `/stop-listening`

**Method:** POST

**Body:**
```json
{
  "group_link": "https://t.me/+abcdef123456"
}
```

**Cevap:**
```json
{
  "success": true,
  "message": "Stopped listening to group: Grup Adı"
}
```

## İlk Kimlik Doğrulama

API'yi ilk kez çalıştırdığınızda, session oluşturmak için kimlik doğrulama yapmanız gerekir:

```bash
python authenticate_telegram.py
```

Bu script, telefonunuza gelen doğrulama kodunu isteyecek ve hem ana istemci hem de dinleyici istemci için gerekli oturum dosyalarını oluşturacaktır.

Ardından API'yi çalıştırabilirsiniz:

```bash
python telegram_api.py
```

## Notlar

- Telethon, Telegram'ın API sınırlamalarına tabidir. Çok fazla mesaj gönderirseniz hesabınız geçici olarak kısıtlanabilir.
- İlk çalıştırmada, Telegram hesabınıza giriş yapmanız ve doğrulama kodunu girmeniz gerekecektir.
- Kullanıcı gizlilik ayarları nedeniyle bazı kullanıcılara mesaj göndermek mümkün olmayabilir.

## Lisans

Bu proje MIT lisansı altında lisanslanmıştır.