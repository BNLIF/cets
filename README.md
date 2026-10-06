# Cold Electronics Tracking System

A monolithic Django project with HTMX, Alpine.js, and Bootstrap.

## Development Setup

1.  **Clone the repository and create a virtual environment:**
    ```bash
    git clone <repository-url>
    cd ce-tracking
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

2.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up environment variables:**
    *   Copy the `.env.example` file to `.env`.
    *   Generate a new `SECRET_key` and update the `.env` file.

4.  **Run database migrations:**
    ```bash
    python manage.py migrate
    ```

## Running the Development Server

1.  **Start the Django development server:**
    *   In a terminal, run:
        ```bash
        python manage.py runserver
        ```

The application will be available at `http://127.0.0.1:8000/`.

## Deployment

The production deployment at BNL runs gunicorn under systemd, fronted by Apache as a reverse proxy.

### Gunicorn systemd unit

Example `/etc/systemd/system/cets.service`:

```ini
[Unit]
Description=gunicorn daemon for cets
After=network.target

[Service]
User=www-data
Group=www-data
RuntimeDirectory=cets
WorkingDirectory=/path/to/cets
ExecStart=/path/to/cets/venv/bin/gunicorn \
          --access-logfile /path/to/cets/tmp/gunicorn.log \
          --workers 3 \
          --bind unix:/run/cets/cets.sock \
          cets.wsgi:application

[Install]
WantedBy=multi-user.target
```

### Apache reverse proxy

Inside the SSL `<VirtualHost>`:

```apache
ProxyPass        /cets/ unix:/run/cets/cets.sock|http://localhost/
ProxyPassReverse /cets/ http://localhost/
RequestHeader set X-Forwarded-Proto "https"
```

Set `FORCE_SCRIPT_NAME=/cets` in `.env` so Django generates URLs under the prefix.

### Deploy ritual

On the server, after pushing to `main`:

```bash
git pull
pip install -r requirements.txt
python manage.py migrate
echo yes | python manage.py collectstatic
sudo systemctl restart cets.service
```

### Ops page

`/hw/ops/` shows who uses the app, the warning log, sync health and machine
facts to the accounts named in the environment; everyone else gets a 404.
The warning log it tails, `cets.log` (warnings and above, rotating), lives
in `CETS_LOG_DIR` (default `tmp/` under the checkout). The service user
must be able to write it; under a tree owned by someone else, pre-create
it once:

```
CETS_OPS_USERS=fnal:chaoz          # in .env; comma-separated Django usernames
touch tmp/cets.log && chmod 666 tmp/cets.log
```

### Cron

Beside the nightly backup (below), one line keeps the Upload-sheet retention
true for users who never come back after a successful upload:

```
0 4 * * * cd /path/to/cets && venv/bin/python manage.py sheet_prune >> tmp/sheet-prune.log 2>&1
```

### SQLite journal

Once per database file, so syncs stop blocking page reads (readers and the
writer no longer wait on each other):

```bash
sqlite3 db.sqlite3 "PRAGMA journal_mode=WAL"
```

Run it with the service stopped (an open connection makes it return `delete`,
unchanged) and check it prints `wal`. It is a property of the file and
survives restarts. `db.sqlite3-wal` and `db.sqlite3-shm` appear beside it on
the first write, with the database's mode and the first opener's owner
(www-data after a restart), and stay while any connection is open — so a
shell user running `migrate`, `dbsize` or a backup against the live database
must share the service's group (`id`; `usermod -aG www-data <user>`, then
a new login — and with ssh multiplexing, `ssh -O exit <host>` first, or the
new session keeps the old connection's groups). Reads still work without it — SQLite falls back to read-only
— so the symptom is only on writes: "attempt to write a readonly database"
from `migrate`, `sheet_prune` or any command that changes rows. The
`-wal` file grows during a long sync and shrinks at the next quiet checkpoint. Back up with `sqlite3 db.sqlite3 ".backup
copy.sqlite3"` rather than copying the file, so the three files stay
consistent — `tools/backup_db.sh <dir> [days]` does that nightly from cron
and rotates the copies. The per-connection pragmas (`synchronous`, `cache_size`,
`transaction_mode`) come from `settings.py`. Not for a database on a
network filesystem.
