import io
import os
import logging
from typing import Dict, Any, List
from datetime import datetime, timezone
import uvicorn
from fastapi import FastAPI, Request, Response, status
from google.cloud import storage
from google.cloud import bigquery
from pypdf import PdfReader

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="GCP Serverless Document Processor")

# Initialize GCP clients
# Note: Clients will use application default credentials (ADC) automatically in Cloud Run.
storage_client = storage.Client()
bq_client = bigquery.Client()

# Read configuration from environment variables
BQ_DATASET = os.getenv("BQ_DATASET", "document_pipeline")
BQ_TABLE = os.getenv("BQ_TABLE", "metadata")

# Keywords for tag extraction
KEYWORD_TAGS = {
    "invoice": "billing",
    "receipt": "billing",
    "payment": "billing",
    "contract": "legal",
    "agreement": "legal",
    "resume": "hr",
    "cv": "hr",
    "tax": "financial",
    "report": "business",
    "budget": "financial",
    "confidential": "security",
    "draft": "status-draft",
    "final": "status-final"
}

def extract_tags(text: str) -> List[str]:
    """Scans the text for keywords and returns matching tags."""
    tags = set()
    text_lower = text.lower()
    for keyword, tag in KEYWORD_TAGS.items():
        if keyword in text_lower:
            tags.add(tag)
    
    # Add generic tags if none matched
    if not tags:
        tags.add("general")
    return list(tags)

def process_file_content(file_bytes: bytes, filename: str, content_type: str) -> Dict[str, Any]:
    """Processes file content (real parsing for text/PDF, simulated OCR for others)."""
    word_count = 0
    text_snippet = ""
    tags = []
    
    # Lowercase filename to check extension as fallback
    fn_lower = filename.lower()
    
    try:
        if content_type.startswith("text/") or fn_lower.endswith(".txt"):
            # Text file: decode and parse
            text = file_bytes.decode("utf-8", errors="ignore")
            word_count = len(text.split())
            text_snippet = text[:200].strip()
            tags = extract_tags(text)
            tags.append("txt")
            logger.info(f"Processed text file '{filename}': {word_count} words.")
            
        elif content_type == "application/pdf" or fn_lower.endswith(".pdf"):
            # PDF file: extract text
            pdf_file = io.BytesIO(file_bytes)
            reader = PdfReader(pdf_file)
            extracted_text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    extracted_text += page_text + " "
            
            extracted_text = extracted_text.strip()
            word_count = len(extracted_text.split())
            text_snippet = extracted_text[:200].strip()
            tags = extract_tags(extracted_text)
            tags.append("pdf")
            logger.info(f"Processed PDF file '{filename}': {word_count} words extracted.")
            
        else:
            # Fallback to simulated OCR (e.g. for images/binary files)
            logger.info(f"Using simulated OCR for binary/unsupported file type: {content_type}")
            simulated_text = (
                f"[SIMULATED OCR SCAN]\n"
                f"File: {filename}\n"
                f"Type: {content_type}\n"
                f"Document recognized as standard invoice/receipt document. "
                f"Extracted metadata: Invoice ID INV-2026-9901. Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}. "
                f"Total amount due: $1,450.00. Tax: $116.00. Status: unpaid. "
                f"Please review billing details."
            )
            word_count = len(simulated_text.split())
            text_snippet = simulated_text[:200].strip()
            tags = extract_tags(simulated_text)
            tags.append("ocr-simulated")
            if fn_lower.endswith((".png", ".jpg", ".jpeg", ".tiff")):
                tags.append("image")
            
    except Exception as e:
        logger.error(f"Error processing content for {filename}: {str(e)}")
        # Fallback to safe defaults
        text_snippet = f"Error extracting content: {str(e)}"
        word_count = 0
        tags = ["error-parsing"]

    return {
        "word_count": word_count,
        "text_snippet": text_snippet,
        "tags": tags
    }

@app.get("/health")
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.post("/", status_code=status.HTTP_200_OK)
async def handle_eventarc_trigger(request: Request):
    """
    Webhook endpoint triggered by Eventarc.
    Parses CloudEvent from headers/body, processes the file, and stores metadata in BigQuery.
    """
    # Eventarc delivers events over HTTP. We parse headers and body.
    headers = request.headers
    body = await request.body()
    
    # Event details from headers (CloudEvents format)
    ce_id = headers.get("ce-id")
    ce_type = headers.get("ce-type")
    ce_source = headers.get("ce-source")
    
    logger.info(f"Received event - ID: {ce_id}, Type: {ce_type}, Source: {ce_source}")
    
    # We only care about storage finalization events
    if ce_type != "google.cloud.storage.object.v1.finalized":
        logger.warning(f"Unsupported event type: {ce_type}. Skipping processing.")
        return {"status": "ignored", "reason": f"Unsupported event type: {ce_type}"}
        
    try:
        event_data = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse JSON body: {str(e)}")
        return Response(content="Invalid JSON payload", status_code=status.HTTP_400_BAD_REQUEST)
        
    bucket_name = event_data.get("bucket")
    object_name = event_data.get("name")
    content_type = event_data.get("contentType", "application/octet-stream")
    file_size = int(event_data.get("size", 0))
    time_created_str = event_data.get("timeCreated")
    
    if not bucket_name or not object_name:
        logger.error("Missing 'bucket' or 'name' fields in event body.")
        return Response(content="Missing bucket or name", status_code=status.HTTP_400_BAD_REQUEST)
        
    logger.info(f"Processing object: gs://{bucket_name}/{object_name}")
    
    # Download file content
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        file_bytes = blob.download_as_bytes()
    except Exception as e:
        logger.error(f"Failed to download gs://{bucket_name}/{object_name}: {str(e)}")
        return Response(content=f"Storage download failed: {str(e)}", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    # Process file and extract metadata
    extraction = process_file_content(file_bytes, object_name, content_type)
    
    # Prepare row for BigQuery insertion
    upload_time = datetime.now(timezone.utc)
    if time_created_str:
        try:
            # Parse RFC3339 format (e.g. 2020-04-23T07:38:57.230Z)
            # Replace 'Z' with UTC timezone offset
            clean_time_str = time_created_str.replace("Z", "+00:00")
            upload_time = datetime.fromisoformat(clean_time_str)
        except Exception as e:
            logger.warning(f"Could not parse timeCreated '{time_created_str}': {str(e)}. Using current time.")

    row = {
        "filename": object_name,
        "bucket_name": bucket_name,
        "upload_timestamp": upload_time.strftime("%Y-%m-%d %H:%M:%S.%f UTC"),
        "content_type": content_type,
        "file_size_bytes": file_size,
        "word_count": extraction["word_count"],
        "tags": extraction["tags"],
        "text_snippet": extraction["text_snippet"]
    }
    
    # Stream insert into BigQuery
    try:
        # Construct table reference: dataset.table
        table_ref = f"{bq_client.project}.{BQ_DATASET}.{BQ_TABLE}"
        errors = bq_client.insert_rows_json(table_ref, [row])
        if errors:
            logger.error(f"BigQuery streaming insert errors: {errors}")
            return Response(content=f"BigQuery insert failed: {errors}", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            logger.info(f"Successfully streamed metadata for {object_name} into BigQuery table {table_ref}")
    except Exception as e:
        logger.error(f"Failed to insert row into BigQuery table: {str(e)}")
        return Response(content=f"BigQuery insert exception: {str(e)}", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    return {
        "status": "success",
        "processed_file": object_name,
        "word_count": extraction["word_count"],
        "tags": extraction["tags"]
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
