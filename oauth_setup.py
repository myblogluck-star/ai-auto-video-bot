import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload"
]

CLIENT_SECRET_FILE = "client_secret.json"


def main():

    if not os.path.exists(CLIENT_SECRET_FILE):
        print(
            "ERROR: client_secret.json not found."
        )
        print(
            "Download your Google OAuth Desktop client JSON "
            "and place it next to this script."
        )
        return

    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        SCOPES
    )

    credentials = flow.run_local_server(
        port=0
    )

    print()
    print("====================================")
    print("YOUTUBE REFRESH TOKEN")
    print("====================================")
    print(credentials.refresh_token)
    print("====================================")
    print()
    print(
        "Copy this token into GitHub Secrets "
        "as YOUTUBE_REFRESH_TOKEN."
    )


if __name__ == "__main__":
    main()
