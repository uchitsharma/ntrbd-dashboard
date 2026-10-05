# B2B NTRBD revenue impact dashboard

> **Before you deploy:** this app serves SKU-level revenue and customer PO detail.
> Streamlit Community Cloud has no access control, so anyone with the URL can read
> whatever is in `data/`. Confirm that is acceptable, or deploy to a private host.

Streamlit dashboard over the FC→DS and FC→RS NTRBD SKU data, May–Aug 2026.

## Run locally

```powershell
cd "C:\Users\Administrator\Documents\NTRBD Impact After-Before - FINAL v1\dashboard"
streamlit run app.py
```

## Deploy to Streamlit Community Cloud

1. `cd` into this `dashboard` folder and init a repo **here** (not the parent — the
   parent holds 90 MB CSVs and the full deliverables).

   ```powershell
   cd "C:\Users\Administrator\Documents\NTRBD Impact After-Before - FINAL v1\dashboard"
   git init
   git add app.py requirements.txt .streamlit data
   git commit -m "NTRBD revenue impact dashboard"
   git branch -M main
   git remote add origin https://github.com/<your-user>/<repo>.git
   git push -u origin main
   ```

2. Push only these paths: `app.py`, `requirements.txt`, `.streamlit/`, `data/`.
   Leave the big CSVs out.

3. Go to <https://share.streamlit.io> → **New app** → pick the repo → deploy.
   The public URL it gives you (`https://<repo>.streamlit.app`) is the link to send.

Deploy settings: *Main file path* `app.py`, *Python version* 3.12, *Requirements*
`requirements.txt`.

## Refresh the data

When a new Metabase export lands, copy it into the **parent** folder with a name the
prep script recognises, then re-run the prep script and push `data/`:

| Flow | Recognised name must contain |
|------|------------------------------|
| DS raw | `raw` + `wh10` or `fc_ds` |
| DS summary | `summary` + `wh10` or `fc_ds` |
| RS raw | `raw` + `fc_rs` |
| RS summary | `summary` + `fc_rs` |

```powershell
python "C:\Users\Administrator\Documents\NTRBD Impact After-Before - FINAL v1\prepare_dashboard_data.py"
```

The RS flow is currently absent, so the Flow filter shows only **FC → DS**. It
activates automatically once the RS exports are dropped in.

## Files

| File | Purpose |
|------|---------|
| `app.py` | The dashboard |
| `data/ntrbd_dashboard.parquet` | PO × SKU × month rows (compressed from ~90 MB CSV to ~2.4 MB) |
| `data/ntrbd_sku_summary.parquet` | Per-SKU before/after |
| `requirements.txt` | Deps for Cloud |
| `.streamlit/config.toml` | Theme + server settings |
| `../prepare_dashboard_data.py` | Rebuilds `data/` from the Metabase exports |
