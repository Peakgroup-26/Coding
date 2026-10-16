# Connecting Xero

About 10 minutes. You need to be an admin in Peak's Xero organisation and have SSH access to the server.

## 1. Make a Xero app (once)

1. Go to **developer.xero.com**, sign in with your Xero login, then **My Apps → New app**.
2. App name: `Peak operations`. Integration type: **Web app**. Company URL: `https://peakgroupdashboard.com.au`.
3. Redirect URI: `https://takeoff.peakgroupdashboard.com.au/api/public/xero-callback`
   (it's shown on the app's Admin → Xero & messages page too).
4. Create the app. Open **Configuration**, copy the **Client id**, and **Generate a secret** and copy it.

## 2. Give them to the server

```bash
cd /opt/peak-takeoff
sudo nano .env
```

Add (or fill in):

```
PUBLIC_URL=https://takeoff.peakgroupdashboard.com.au
XERO_CLIENT_ID=the client id
XERO_CLIENT_SECRET=the secret
```

Save (Ctrl+O, Enter, Ctrl+X), then `sudo docker compose up -d`.

## 3. Connect

In the app: **Admin → Xero & messages → Connect to Xero**. Sign in to Xero, pick Peak's organisation, and allow access.
You come back to the app and the first sync runs straight away.

## What it does

Every 15 minutes (and when you press **Sync now**):

| | |
|---|---|
| Invoices sent in the app | go to Xero as sales invoices, same number, job number in the reference |
| Payments in Xero | mark the invoice paid in the app |
| Supplier bills in Xero quoting a PO number (e.g. `J26-0012-PO3`) | bill that PO; the cost lands on the job |
| Supplier bills quoting a job number | become a cost on that job |
| Sales invoices raised in Xero quoting a job number | count as that job's revenue |
| Bank accounts | the total becomes the cash flow forecast's starting balance |

Anything else in Xero (overheads, wages) stays in Xero. The app never deletes anything in Xero.

Set the sales account code, tax type and whether invoices arrive approved or as drafts on the same Admin page.

**Scopes:** Xero apps made after 2 March 2026 must use Xero's granular permission scopes. The app asks for
`accounting.contacts accounting.invoices accounting.payments accounting.banktransactions.read accounting.settings.read accounting.reports.read`.
If Xero changes these, set `XERO_SCOPES` in `.env` to what Xero's Scopes page lists and reconnect.

## Reece maX

Reece only connects maX directly to software it has approved as a partner (Simpro, AroFlo and the like). Until Peak's app is
approved, download the price file from maX each month and load it under **Purchasing → Supplier price files** (tick
*Reece maX file*). Reece invoices reach the app through Xero: when they quote the PO number they're matched to the PO.
