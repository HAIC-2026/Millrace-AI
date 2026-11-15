# Reopen a public33af case

The earlier public snapshot is self-contained at Git commit `e2f2cf031fe7f193de08524a9ce49d5d5f14b5d4`. Its combined evidence identity is `sha256:33af0580ddd697fbe16dedf1b335303cfc9a4e958df5c684f1eade8365dd6aa3`.

Create a separate checkout outside the current source tree:

```sh
git clone https://github.com/HAIC-2026/Millrace-AI.git /absolute/new-public33af-replay
git -C /absolute/new-public33af-replay checkout --detach e2f2cf031fe7f193de08524a9ce49d5d5f14b5d4
cd /absolute/new-public33af-replay
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
HAIC_STATE_DIR=/absolute/separate-public33af-state HAIC_LOCAL_HTTP=1 PORT=8083 .venv/bin/gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8083 wsgi:application
```

Open [the local public33af app](http://127.0.0.1:8083). Choose your saved case file, inspect its preview, then explicitly replay it. Imported staff work requires review before a brief. No private archive or provider credential is required.

Use the matching R2 application or retained-input profile for R2 cases. This checkout does not admit R2 cases through its default public profile. New evidence requires a blank investigation. Preserve each saved file and use its matching evidence snapshot.
