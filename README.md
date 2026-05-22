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
