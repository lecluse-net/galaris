import sys
import http.client

def health_check() -> None:
    # Probe the backend locally so its health never depends on the frontend
    # container. Readiness includes PostgreSQL and critical root services.
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=5)
    try:
        conn.request("GET", "/api/health/ready")
        response = conn.getresponse()
        
        if response.status == 200:
            sys.exit(0)
        else:
            print(f"Healthcheck failed: {response.status} {response.reason}")
            sys.exit(1)
    except Exception as e:
        print(f"Healthcheck exception: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    health_check()
