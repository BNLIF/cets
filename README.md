# Cold Electronics Tracking System

A monolithic Django project with HTMX, Alpine.js, and Tailwind CSS.

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
    *   Generate a new `SECRET_KEY` and update the `.env` file.

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