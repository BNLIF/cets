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

These instructions are for deploying the application on a server using Apache.

### Apache Setup

1.  **Install Apache and mod_wsgi:**
    ```bash
    # On Debian/Ubuntu
    sudo apt-get update
    sudo apt-get install apache2 libapache2-mod-wsgi-py3

    # On RHEL/CentOS
    sudo yum install httpd mod_wsgi
    ```

2.  **Configure Apache:**
    *   Create a new configuration file for your site in `/etc/apache2/sites-available/cets.conf` (Debian/Ubuntu) or `/etc/httpd/conf.d/cets.conf` (RHEL/CentOS).
    *   Add the following content to the file, replacing the placeholders with your actual paths and domain name:

    ```apache
    <VirtualHost *:80>
        ServerName your_domain.com
        ServerAlias www.your_domain.com

        Alias /static/ /path/to/your/project/static/
        <Directory /path/to/your/project/static>
            Require all granted
        </Directory>

        <Directory /path/to/your/project/cets>
            <Files wsgi.py>
                Require all granted
            </Files>
        </Directory>

        WSGIDaemonProcess cets python-home=/path/to/your/project/venv python-path=/path/to/your/project
        WSGIProcessGroup cets
        WSGIScriptAlias / /path/to/your/project/cets/wsgi.py
    </VirtualHost>
    ```

3.  **Enable the site and restart Apache:**
    ```bash
    # On Debian/Ubuntu
    sudo a2ensite cets.conf
    sudo systemctl restart apache2

    # On RHEL/CentOS
    sudo systemctl restart httpd
    ```

4.  **Collect Static Files:**
    Before starting the server, you need to collect all static files into a single directory.
    ```bash
    python manage.py collectstatic
    ```
