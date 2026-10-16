# Connecting Geotab (the vehicle map)

About 10 minutes. You need to be an administrator in MyGeotab and have SSH access to the server.

## 1. Make a read-only user for Lorojo (once)

1. In MyGeotab go to **People → Add**.
2. User (email): something like `lorojo-api@peakpcg.com.au`. It doesn't need a real mailbox.
3. Security clearance: **View only** (or a custom clearance that can view vehicles, trips and drivers).
4. Data access: the groups with the vehicles you want on the map (usually the whole company).
5. Set a long password and untick "must change password at next log in". Save.
6. Note the **database name**. It's shown at the top left of MyGeotab, and in the address bar after `my.geotab.com/`.

## 2. Give them to the server

Don't send these to anyone (or paste them into a chat). Type them straight into the server:

```bash
cd /opt/peak-takeoff
sudo nano .env
```

Add:

```
GEOTAB_DATABASE=your database name
GEOTAB_USERNAME=lorojo-api@peakpcg.com.au
GEOTAB_PASSWORD=the password
```

`GEOTAB_SERVER` defaults to `my.geotab.com`. Lorojo follows Geotab's redirect to your own server automatically.

Save (Ctrl+O, Enter, Ctrl+X), then run `sudo docker compose up -d`.

## 3. Check it

Open **Operations → Vehicle map**. Every vehicle should show on the map within a few seconds.

Vehicles are matched to the plant register by rego, then VIN (the plant record's serial number), then name. To link any that
don't match, use **Link to plant records**. A linked vehicle shows who it's assigned to (tap to call) and opens its plant record.

If the page says "Couldn't reach Geotab", check the three values and that the user isn't locked out.
