# Putting Peak Take-off on the Plesk server

This puts the app at **https://takeoff.peakgroupdashboard.com.au**, next to the existing dashboard, without touching it.
It takes about an hour. You need:

- Admin access to Plesk for peakgroupdashboard.com.au.
- SSH (terminal) access to the server as a user that can use `sudo`. In Plesk this is under **Tools & Settings → SSH Terminal**, if that extension is installed.
- A GitHub account that can see the `Peakgroup-26/Coding` repository.
- An Anthropic API key for the AI reading (console.anthropic.com → API keys). Keep it out of email and chat: you'll paste it straight into the server in step 3.

The server needs at least 4 GB of RAM and 20 GB free disk. Plans take roughly 5–20 MB per set once rendered.

## 1. Make the subdomain

1. In Plesk go to **Websites & Domains → Add Subdomain**.
2. Subdomain name: `takeoff`. Parent domain: `peakgroupdashboard.com.au`. Leave the document root as it is.
3. If your DNS isn't hosted by Plesk, add an **A record** for `takeoff` pointing at the server's IP address with whoever hosts your DNS.

## 2. Turn on HTTPS

1. Open the new subdomain in Plesk, then **SSL/TLS Certificates**.
2. Choose **Install** under *Let's Encrypt* (free), tick *Secure the domain*, and confirm.
3. Under **Hosting Settings**, turn on **Permanent SEO-safe 301 redirect from HTTP to HTTPS**.

## 3. Install the app (SSH)

Run these one block at a time.

**a. Give the server read-only access to the code.** The repository is private, so the server needs its own key:

```bash
sudo ssh-keygen -t ed25519 -N "" -f /root/.ssh/peak_takeoff_deploy
sudo cat /root/.ssh/peak_takeoff_deploy.pub
```

Copy the line it prints. On GitHub, open the repository → **Settings → Deploy keys → Add deploy key**, paste it, name it
"Plesk server", and leave *Allow write access* **unticked**.

**b. Download the code:**

```bash
sudo GIT_SSH_COMMAND="ssh -i /root/.ssh/peak_takeoff_deploy -o StrictHostKeyChecking=accept-new" \
  git clone git@github.com:Peakgroup-26/Coding.git /opt/peak-takeoff
cd /opt/peak-takeoff
sudo git config core.sshCommand "ssh -i /root/.ssh/peak_takeoff_deploy"
```

**c. Install and start it:**

```bash
sudo ./deploy/install.sh
```

The script:

- installs Docker if it isn't there yet;
- asks for your email and the Anthropic API key;
- makes random passwords for the database and your first login, and **prints your login password once**, so write it down;
- builds and starts the app and its database;
- sets up a nightly backup.

The first build takes 5–10 minutes. At the end it prints the port the app is using, normally `8000`.

## 4. Point the subdomain at the app

1. In Plesk, open `takeoff.peakgroupdashboard.com.au` → **Apache & nginx Settings**.
2. Scroll to **Additional nginx directives** and paste everything from [`nginx-directives.conf`](nginx-directives.conf). If the install script printed a port other than 8000, change `8000` to match.
3. Click **OK**. Plesk checks the settings before applying them.

If Plesk shows an error when saving, use **Docker → Docker Proxy Rules** on the subdomain instead (if your Plesk has the Docker extension). Add a rule for URL `/`, container `peak-takeoff-app-1`, port `8000`.

## 5. Sign in

Go to **https://takeoff.peakgroupdashboard.com.au** and sign in with the email and password from step 3c.
Then change your password (**My account**) and add your team in **Admin → People & permissions**. Give the
people on the tools the **On the tools** role: they get only the phone app. Send them to
**https://takeoff.peakgroupdashboard.com.au/field** on their phone and have them add it to their home screen.

Then: connect Xero ([XERO.md](XERO.md)), set up email for customer follow-ups (`SMTP_...` in `.env`), and set your
company name and Google review link in **Admin → Operations & plant**.

## Day to day

| Task | Command (from `/opt/peak-takeoff`) |
|---|---|
| Update to the latest version | `sudo ./deploy/update.sh` (backs up first) |
| Back up now | `sudo ./deploy/backup.sh` |
| See if it's running | `sudo docker compose ps` |
| Look at the logs | `sudo docker compose logs --tail 100 app` |
| Restart | `sudo docker compose restart app` |
| Change a setting (e.g. the AI key) | `sudo nano .env`, then `sudo docker compose up -d` |

**Backups:** these go to `/var/backups/peak-takeoff` every night and are kept for 14 days. They hold the database,
the drawings and the settings file. Also copy that folder off the server, for example by adding it to Plesk's
**Backup Manager** remote storage. A backup that only lives on the same server won't survive losing the server.

**Security:** the app only listens inside the server (`127.0.0.1`). The only way in from outside is through Plesk's
HTTPS website. Drawings are only ever served to signed-in users. The settings file `.env` holds the passwords and API
key; it's readable by root only and is never committed to GitHub.

## Optional: Microsoft 365 sign-in

Your IT provider registers an app in Microsoft Entra ID with this redirect URI:

```
https://takeoff.peakgroupdashboard.com.au/api/auth/sso/callback
```

Then put the tenant ID, client ID and client secret in `.env` (`SSO_TENANT_ID`, `SSO_CLIENT_ID`, `SSO_CLIENT_SECRET`), set
`SSO_REDIRECT_URI` to the address above and `SSO_ALLOWED_DOMAINS=peakpcg.com.au`, then run `sudo docker compose up -d`.
