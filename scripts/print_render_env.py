from pathlib import Path
import base64


def print_encoded_file(env_name: str, path: str) -> None:
    data = Path(path).read_bytes()
    encoded = base64.b64encode(data).decode("utf-8")
    print(f"{env_name}={encoded}")


if __name__ == "__main__":
    print_encoded_file("GOOGLE_OAUTH_CLIENT_JSON", "credentials/google_oauth_client.json")
    print_encoded_file("GOOGLE_TOKEN_JSON", "credentials/google_token.json")
