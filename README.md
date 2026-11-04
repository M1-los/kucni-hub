# 🏠 Kućni Hub & Asistent (Rutina, Čišćenje i Nabavka)

Minimalistički, moderan i interaktivan sistem za organizaciju stana, poslova čišćenja i spiskova nabavke za tebe i tvoju sestru, povezan sa Telegram botom.

---

## 🚀 Kako pokrenuti aplikaciju

Server je već pokrenut u pozadini! Ako ga nekada ugasiš, možeš ga ponovo pokrenuti komandom:

```bash
cd /Users/miloscivic/.gemini/antigravity/scratch/kucni-hub
./start.sh
```

Ili direktno:
```bash
python3 server.py
```

---

## 📱 Kako pristupiti aplikaciji

1. **Na tvom MacBook-u**: Otvori u pretraživaču:
   👉 **[http://localhost:8000](http://localhost:8000)**

2. **Na tvom telefonu i sestrinom telefonu (ista Wi-Fi kućna mreža)**:
   👉 **http://192.168.0.11:8000**
   
   *(Savet: U Safariju na iPhone-u kliknite na **Share** ➔ **Add to Home Screen** kako biste dobili aplikaciju sa ikonicom na ekranu!)*

---

## 🤖 Kako povezati Telegram Bota (30 sekundi)

1. Otvori **Telegram** na telefonu ili kompjuteru.
2. U pretrazi pronađi **`@BotFather`** i klikni **Start**.
3. Pošalji mu poruku:
   ```
   /newbot
   ```
4. Izaberi ime za bota (npr. *Naš Kućni Asistent*).
5. Izaberi korisničko ime koje se završava na `bot` (npr. *milos_kucni_bot*).
6. `@BotFather` će ti poslati **HTTP API Token** (dugačak niz slova i brojeva).
7. Otvori svoj **Kućni Hub sajt**, idi na tab **🤖 Telegram**, unesi token i klikni **Sačuvaj podešavanja**.
8. Napravi Telegram grupu sa sestrom, ubacite vašeg bota i pošaljite komandu:
   ```
   /start
   ```

---

## 💬 Šta bot sve može u Telegramu?

U vašoj grupi ili direktnom četu možete mu slati:

- **`/kupi mleko`** ili **`/kupi domestos`** — bot automatski prepoznaje da li je u pitanju hrana ili hemija i stavlja na spisak na vašem sajtu!
- **`/spisak`** ili **`/nabavka`** — bot vraća uredno formatiran spisak svega što trenutno fali u kući.
- **`/zadaci`** — prikazuje šta je za danas ostalo od poslova.
- **🌅 Jutarnji podsetnik** — bot automatski svakog jutra (podrazumevano u 09:00) šalje poruku u vašu grupu sa fokusom dana (npr. Utorak = Kupatilo i kamenac, Petak = Usisavanje i pranje podova).

---

## 📁 Struktura fajlova

- `server.py` — Python backend sa ugrađenom SQLite bazom, Telegram polling radnikom i planerom jutarnjih podsetnika.
- `public/index.html` — Minimalistički Tailwind CSS frontend prilagođen za mobilni i desktop.
- `kucnihub.db` — Baza podataka koja čuva sve vaše zadatke, spiskove, istoriju i podešavanja.
- `start.sh` — Skripta za brzo pokretanje.
