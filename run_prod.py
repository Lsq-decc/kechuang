import os

from app import create_app


app = create_app()


if __name__ == "__main__":
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))
    threads = int(os.getenv("WAITRESS_THREADS", "8"))

    print(f"Server listening on http://{host}:{port}")
    try:
        from waitress import serve
    except ImportError:
        from werkzeug.serving import make_server

        print("Waitress is not installed; using the threaded development server.")
        server = make_server(host, port, app, threaded=True)
        server.serve_forever()
    else:
        serve(
            app,
            host=host,
            port=port,
            threads=threads,
            channel_timeout=300,
            clear_untrusted_proxy_headers=True,
        )
