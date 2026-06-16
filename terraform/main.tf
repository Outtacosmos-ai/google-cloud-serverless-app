locals {
  apis = [
    "run.googleapis.com",
    "storage.googleapis.com",
    "eventarc.googleapis.com",
    "pubsub.googleapis.com",
    "bigquery.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com"
  ]
}

# Enable GCP Services
resource "google_project_service" "services" {
  for_each = toset(local.apis)
  project  = var.project_id
  service  = each.value

  disable_on_destroy = false
}

# Artifact Registry Repository to hold Docker Images
resource "google_artifact_registry_repository" "repo" {
  provider      = google-beta
  location      = var.region
  repository_id = "document-pipeline-repo"
  description   = "Docker repository for serverless document pipeline"
  format        = "DOCKER"

  depends_on = [google_project_service.services]
}

# Google Cloud Storage Bucket for file uploads
resource "google_storage_bucket" "upload_bucket" {
  name          = var.bucket_name
  location      = var.region
  force_destroy = true # Allows easy cleanup of files when deleting bucket

  uniform_bucket_level_access = true

  depends_on = [google_project_service.services]
}

# BigQuery Dataset
resource "google_bigquery_dataset" "dataset" {
  dataset_id                  = var.dataset_id
  friendly_name               = "Document pipeline dataset"
  description                 = "Contains extracted metadata from processed files"
  location                    = var.region
  default_table_expiration_ms = 3600000 * 24 * 365 # 1 year

  depends_on = [google_project_service.services]
}

# BigQuery Table
resource "google_bigquery_table" "metadata_table" {
  dataset_id          = google_bigquery_dataset.dataset.dataset_id
  table_id            = var.table_id
  deletion_protection = false # Allows terraform destroy to remove table

  schema = <<EOF
[
  {
    "name": "filename",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "Name of the processed file"
  },
  {
    "name": "bucket_name",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "GCS bucket where file was uploaded"
  },
  {
    "name": "upload_timestamp",
    "type": "TIMESTAMP",
    "mode": "REQUIRED",
    "description": "Timestamp when file was uploaded"
  },
  {
    "name": "content_type",
    "type": "STRING",
    "mode": "NULLABLE",
    "description": "MIME type of the file"
  },
  {
    "name": "file_size_bytes",
    "type": "INTEGER",
    "mode": "NULLABLE",
    "description": "Size of the file in bytes"
  },
  {
    "name": "word_count",
    "type": "INTEGER",
    "mode": "NULLABLE",
    "description": "Total word count of the file"
  },
  {
    "name": "tags",
    "type": "STRING",
    "mode": "REPEATED",
    "description": "Extracted keyword tags"
  },
  {
    "name": "text_snippet",
    "type": "STRING",
    "mode": "NULLABLE",
    "description": "The first 200 characters of extracted text"
  }
]
EOF

  depends_on = [google_bigquery_dataset.dataset]
}

# -----------------------------------------------------------------------------
# Service Account & IAM roles for Cloud Run
# -----------------------------------------------------------------------------

resource "google_service_account" "cloud_run_sa" {
  account_id   = "doc-processor-sa"
  display_name = "Cloud Run Document Processor Service Account"

  depends_on = [google_project_service.services]
}

# Grant Storage Object Viewer to Cloud Run
resource "google_storage_bucket_iam_member" "gcs_viewer" {
  bucket = google_storage_bucket.upload_bucket.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

# Grant BigQuery Data Editor to Cloud Run at Dataset level
resource "google_project_iam_member" "bq_editor" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

# -----------------------------------------------------------------------------
# Service Account & IAM roles for Eventarc Trigger
# -----------------------------------------------------------------------------

resource "google_service_account" "eventarc_sa" {
  account_id   = "eventarc-trigger-sa"
  display_name = "Eventarc Trigger Service Account"

  depends_on = [google_project_service.services]
}

# Grant Eventarc Receiver to the Eventarc service account
resource "google_project_iam_member" "eventarc_receiver" {
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.eventarc_sa.email}"
}

# Grant Run Invoker to the Eventarc service account to invoke Cloud Run
resource "google_project_iam_member" "eventarc_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.eventarc_sa.email}"
}

# GCS Service Agent publishing permissions: GCS needs to be able to publish to Pub/Sub
# (Eventarc uses GCS notifications to Pub/Sub under the hood)
data "google_storage_project_service_account" "gcs_account" {
  project = var.project_id
  depends_on = [google_project_service.services]
}

resource "google_project_iam_member" "gcs_pubsub_publishing" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"
}

# -----------------------------------------------------------------------------
# Cloud Run Service & Eventarc Trigger
# -----------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "processor" {
  name     = "document-processor"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY" # Only internal/Eventarc traffic should trigger it

  template {
    service_account = google_service_account.cloud_run_sa.email

    containers {
      # Points to the image built & pushed in the Artifact Registry repository.
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.name}/doc-processor:latest"

      env {
        name  = "BQ_DATASET"
        value = var.dataset_id
      }
      env {
        name  = "BQ_TABLE"
        value = var.table_id
      }

      ports {
        container_port = 8080
      }
    }
  }

  depends_on = [
    google_artifact_registry_repository.repo,
    google_service_account.cloud_run_sa
  ]
}

resource "google_eventarc_trigger" "gcs_trigger" {
  name     = "gcs-file-upload-trigger"
  location = var.region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }

  matching_criteria {
    attribute = "bucket"
    value     = google_storage_bucket.upload_bucket.name
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_v2_service.processor.name
      region  = var.region
    }
  }

  service_account = google_service_account.eventarc_sa.email

  depends_on = [
    google_cloud_run_v2_service.processor,
    google_project_iam_member.eventarc_receiver,
    google_project_iam_member.eventarc_invoker,
    google_project_iam_member.gcs_pubsub_publishing
  ]
}
