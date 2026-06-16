# Google Cloud Serverless Document Pipeline

An event-driven, serverless pipeline built on Google Cloud Platform (GCP) that automatically ingests, processes, and extracts metadata from documents using Python, FastAPI, and BigQuery. Entirely provisioned using Terraform (Infrastructure as Code).

## 🚀 Architecture Overview

This project implements a fully automated pipeline:
1. **Ingestion:** A user or system uploads a document (PDF, TXT) to a Google Cloud Storage (GCS) bucket.
2. **Trigger:** Eventarc detects the `object.v1.finalized` event and securely routes the payload.
3. **Processing:** A serverless Cloud Run container (FastAPI/Python) scales from zero to intercept the event, downloads the file, and extracts structural text and metadata (file size, word count, MIME type).
4. **Data Warehousing:** The extracted metadata is streamed directly into a BigQuery dataset for analytics and reporting.

### Tech Stack
* **Infrastructure as Code:** Terraform
* **Compute:** Google Cloud Run (Docker, Serverless)
* **Storage & Analytics:** Google Cloud Storage, Google BigQuery
* **Event Routing:** Google Eventarc, Pub/Sub
* **Backend:** Python 3.11, FastAPI, PyPDF

---

## 📁 Repository Structure

```text
.
├── src/
│   ├── main.py              # FastAPI application handling Eventarc triggers
│   ├── requirements.txt     # Python dependencies
│   └── Dockerfile           # Container specification for Cloud Run
├── terraform/
│   ├── main.tf              # Terraform configuration for all GCP resources
│   └── variables.tf         # Variable definitions
├── .gitignore
└── README.md
```

---

## 🛠️ Prerequisites

Before deploying, ensure you have the following installed and configured:
* Google Cloud CLI (`gcloud`) authenticated with a billing-enabled GCP Project.
* Terraform (v1.0+)
* Docker (for local builds, or use Google Cloud Build)

---

## ⚙️ Deployment Instructions

### 1. Build and Push the Container Image
Terraform requires the Docker image to exist in the Artifact Registry before it can deploy the Cloud Run service. 

Authenticate Docker with Google Cloud:
```bash
gcloud auth configure-docker us-central1-docker.pkg.dev --quiet
```

Build and push the image natively from the root directory:
```bash
docker build -t us-central1-docker.pkg.dev/<YOUR_PROJECT_ID>/document-pipeline-repo/doc-processor:latest ./src/
docker push us-central1-docker.pkg.dev/<YOUR_PROJECT_ID>/document-pipeline-repo/doc-processor:latest
```

### 2. Provision Infrastructure with Terraform
Navigate to the `/terraform` directory and initialize the environment:
```bash
cd terraform
terraform init
```

Deploy the full architecture:
```bash
terraform apply -var="project_id=<YOUR_PROJECT_ID>" -var="bucket_name=<YOUR_UNIQUE_BUCKET_NAME>"
```
*Type `yes` when prompted to create the ~20 GCP resources.*

---

## 🧪 Testing the Pipeline

Once deployed, the architecture is fully event-driven and requires no manual execution.

1. **Upload a Document:** Navigate to your GCS bucket in the Google Cloud Console and upload a sample PDF or Text file.
2. **Verify Extraction:** Open BigQuery Studio and query your metadata table:
```sql
SELECT * FROM `<YOUR_PROJECT_ID>.document_pipeline.metadata`
```
*You will instantly see a new row containing the extracted metadata for your uploaded document.*

---

## 🧹 Cost Optimization & Cleanup

To ensure zero lingering costs on your Google Cloud billing account, tear down the infrastructure when not in use. Terraform handles the complete destruction of all associated resources.

```bash
terraform destroy -var="project_id=<YOUR_PROJECT_ID>" -var="bucket_name=<YOUR_UNIQUE_BUCKET_NAME>"
```

---
*Architected and deployed by Mohamed ESSRHIR.*
