import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Set environment variables before importing main to prevent client initialization failures
os.environ["BQ_DATASET"] = "test_dataset"
os.environ["BQ_TABLE"] = "test_table"
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "mock_creds.json" # dummy credentials path

# Add src to python path so we can import main
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

# Patch google clients before importing main to prevent actual GCP connection attempts
storage_patcher = patch("google.cloud.storage.Client")
bigquery_patcher = patch("google.cloud.bigquery.Client")
mock_storage_client = storage_patcher.start()
mock_bigquery_client = bigquery_patcher.start()

import main
from main import extract_tags, process_file_content

class TestDocumentProcessor(unittest.TestCase):

    def tearDown(self):
        # Reset mocks
        mock_storage_client.reset_mock()
        mock_bigquery_client.reset_mock()

    def test_extract_tags(self):
        """Test tag extraction based on keywords."""
        text_with_invoice = "This is a billing invoice for services rendered."
        tags = extract_tags(text_with_invoice)
        self.assertIn("billing", tags)

        text_with_contract = "A signed agreement or contract."
        tags = extract_tags(text_with_contract)
        self.assertIn("legal", tags)

        text_with_no_keywords = "Random text here with nothing special."
        tags = extract_tags(text_with_no_keywords)
        self.assertEqual(tags, ["general"])

    def test_process_file_content_txt(self):
        """Test processing a plain text file."""
        content = b"This is a final draft of the report. It contains 10 words."
        filename = "test_doc.txt"
        content_type = "text/plain"
        
        result = process_file_content(content, filename, content_type)
        
        self.assertEqual(result["word_count"], 12) # This is a final draft of the report. It contains 10 words. -> 12 words
        self.assertIn("status-draft", result["tags"])
        self.assertIn("status-final", result["tags"])
        self.assertIn("business", result["tags"])
        self.assertIn("txt", result["tags"])
        self.assertTrue(result["text_snippet"].startswith("This is a final draft"))

    def test_process_file_content_image(self):
        """Test simulated OCR processing for an image."""
        content = b"\x89PNG\r\n\x1a\n..." # Dummy image bytes
        filename = "receipt.png"
        content_type = "image/png"
        
        result = process_file_content(content, filename, content_type)
        
        self.assertGreater(result["word_count"], 0)
        self.assertIn("ocr-simulated", result["tags"])
        self.assertIn("image", result["tags"])
        self.assertIn("billing", result["tags"]) # Simulated OCR contains "billing" keywords
        self.assertTrue(result["text_snippet"].startswith("[SIMULATED OCR SCAN]"))

    @patch("main.storage_client")
    @patch("main.bq_client")
    def test_webhook_unsupported_event(self, mock_bq, mock_storage):
        """Test webhook endpoint with an unsupported Eventarc event."""
        from fastapi.testclient import TestClient
        client = TestClient(main.app)

        headers = {
            "ce-id": "1234",
            "ce-type": "google.cloud.storage.object.v1.deleted", # Unsupported event
            "ce-source": "storage.googleapis.com",
        }
        payload = {
            "bucket": "my-bucket",
            "name": "file.txt"
        }

        response = client.post("/", json=payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ignored", "reason": "Unsupported event type: google.cloud.storage.object.v1.deleted"})
        mock_storage.bucket.assert_not_called()

    @patch("main.storage_client")
    @patch("main.bq_client")
    def test_webhook_successful_processing(self, mock_bq, mock_storage):
        """Test webhook endpoint with a valid Eventarc GCS upload event."""
        from fastapi.testclient import TestClient
        client = TestClient(main.app)

        # Mock storage download
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_blob.download_as_bytes.return_value = b"Hello world! This is a simple test document containing an invoice."
        mock_bucket.blob.return_value = mock_blob
        mock_storage.bucket.return_value = mock_bucket

        # Mock BigQuery insertion
        mock_bq.project = "test-project"
        mock_bq.insert_rows_json.return_value = [] # No errors

        headers = {
            "ce-id": "5678",
            "ce-type": "google.cloud.storage.object.v1.finalized",
            "ce-source": "storage.googleapis.com",
        }
        payload = {
            "bucket": "my-test-bucket",
            "name": "invoice_document.txt",
            "contentType": "text/plain",
            "size": "67",
            "timeCreated": "2026-06-16T12:00:00.000Z"
        }

        response = client.post("/", json=payload, headers=headers)
        
        self.assertEqual(response.status_code, 200)
        resp_data = response.json()
        self.assertEqual(resp_data["status"], "success")
        self.assertEqual(resp_data["processed_file"], "invoice_document.txt")
        self.assertIn("billing", resp_data["tags"])
        
        # Verify GCS download was called
        mock_storage.bucket.assert_called_once_with("my-test-bucket")
        mock_bucket.blob.assert_called_once_with("invoice_document.txt")
        
        # Verify BigQuery insert was called
        mock_bq.insert_rows_json.assert_called_once()
        insert_args = mock_bq.insert_rows_json.call_args[0]
        self.assertEqual(insert_args[0], "test-project.test_dataset.test_table")
        row = insert_args[1][0]
        self.assertEqual(row["filename"], "invoice_document.txt")
        self.assertEqual(row["bucket_name"], "my-test-bucket")
        self.assertEqual(row["content_type"], "text/plain")
        self.assertEqual(row["file_size_bytes"], 67)
        self.assertIn("billing", row["tags"])

if __name__ == "__main__":
    unittest.main()

# Stop patchers
storage_patcher.stop()
bigquery_patcher.stop()
