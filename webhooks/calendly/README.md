# Calendly webhook service

Receives Calendly `invitee.created` / `invitee.canceled` and updates Supabase candidates.

- **Production:** [RENDER.md](./RENDER.md) (Render Blueprint via repo `render.yaml`)
- **Full setup:** [../../integrations/calendly-setup.md](../../integrations/calendly-setup.md)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8089
```
