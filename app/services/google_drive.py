from __future__ import annotations

import io
from dataclasses import dataclass

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from app.services.google_auth import BASE_SCOPES, DRIVE_SCOPES, get_google_credentials


SPREADSHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


@dataclass
class GoogleDriveService:
    def __post_init__(self) -> None:
        self.client = build(
            "drive",
            "v3",
            credentials=get_google_credentials(BASE_SCOPES + DRIVE_SCOPES),
        )

    def get_parent_folder_id(self, file_id: str) -> str:
        metadata = (
            self.client.files()
            .get(fileId=file_id, fields="parents", supportsAllDrives=True)
            .execute()
        )
        parents = metadata.get("parents", [])
        return parents[0] if parents else ""

    def find_or_create_spreadsheet(self, name: str, parent_folder_id: str = "") -> str:
        escaped_name = name.replace("'", "\\'")
        query_parts = [
            f"name = '{escaped_name}'",
            f"mimeType = '{SPREADSHEET_MIME_TYPE}'",
            "trashed = false",
        ]
        if parent_folder_id:
            query_parts.append(f"'{parent_folder_id}' in parents")
        result = (
            self.client.files()
            .list(
                q=" and ".join(query_parts),
                fields="files(id, name)",
                spaces="drive",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = result.get("files", [])
        if files:
            return files[0]["id"]

        metadata: dict[str, object] = {
            "name": name,
            "mimeType": SPREADSHEET_MIME_TYPE,
        }
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]
        created = (
            self.client.files()
            .create(body=metadata, fields="id", supportsAllDrives=True)
            .execute()
        )
        return created["id"]

    def upload_receipt(
        self,
        filename: str,
        content_type: str,
        data: bytes,
        parent_folder_id: str = "",
    ) -> str:
        metadata: dict[str, object] = {"name": filename}
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=content_type, resumable=False)
        created = (
            self.client.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        return created.get("webViewLink", "")
