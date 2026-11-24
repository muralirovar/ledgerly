# Running Ledgerly on a Mac, and sharing a business between two Macs

Each Mac runs its own copy of Ledgerly with its own database and its own logins. One business is edited on
**one** Mac only. Once a month the Mac that edits it sends a business file to the other.

## One-time setup on each Mac
1. Turn on **FileVault** (System Settings → Privacy & Security). The database file is protected by this, not by the app login.
2. Install Docker Desktop (or Colima), then get the app:
   ```bash
   git clone https://github.com/muralirovar/ledgerly.git
   cd ledgerly
   docker compose up -d --build
   ```
   Both Macs must run the **same version**. Run `git pull && docker compose up -d --build` on both before each exchange.
3. Open <http://localhost:8501>. The first screen creates the **owner** account: choose a username and a password of 12+ characters,
   scan the QR code with an authenticator app, type the 6-digit code, and **save the 8 recovery codes**.
4. Keep the Mac awake while you use it, and let Time Machine back up the `data` folder.

Locked out and out of recovery codes? On that Mac: `docker exec -it business-books python -m books.auth_cli reset USERNAME`.

## Starting the accountant's copy (once)
1. On your Mac: **Setup → Share a business → Export**. Pick the 2 businesses he will manage, type a password for the file, press
   **Prepare files**, download both.
2. Send the files by one route and the file password by another (for example email the files and text the password).
3. On his Mac, after creating his owner account: **Setup → Share a business → Import a business**, choose a file, enter the
   password, check the preview, tick the box, press **Import**. Repeat for the second file. A backup is saved before each import.
4. From now on those 2 businesses are **his**. Do not edit them on your Mac. Keep the other 2 businesses to yourself: they are not on his Mac.

## Every month
1. **He** exports his 2 businesses (same screen, with a password) and sends you the files.
2. **You** import them. The preview shows what will be replaced. If it warns that your copy has changes made after his export,
   stop: someone edited the business on your Mac, and importing would discard that.
3. Your Mac now shows his current books for those 2 businesses (reports, 1099 vendors, summary sheet, audit and so on).

## What travels in a business file
Accounts, transactions (with splits and attachments), categories, rules, parties, checks and statements, loan notes, staff
and payroll matches, mileage. Not included: login accounts, the access audit log, app settings and personal tax prep.

## Good habits
- Delete old business files after importing. They contain the whole business.
- Use a different password for each file exchange if you can, and never put the password in the same message as the file.
- Check **Setup → Access audit** now and then to see sign-ins and failed attempts on your Mac.
