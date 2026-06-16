output "artifact_registry_repo" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.name}"
  description = "The path to the Artifact Registry repository."
}

output "gcs_bucket_name" {
  value       = google_storage_bucket.upload_bucket.name
  description = "The name of the GCS upload bucket."
}

output "bigquery_table" {
  value       = "${google_bigquery_dataset.dataset.dataset_id}.${google_bigquery_table.metadata_table.table_id}"
  description = "The BigQuery table name."
}

output "cloud_run_url" {
  value       = google_cloud_run_v2_service.processor.uri
  description = "The URL of the Cloud Run processor service."
}

output "docker_build_command" {
  value       = "gcloud builds submit ../src --tag ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.name}/doc-processor:latest --project=${var.project_id}"
  description = "Command to build the container image and upload it to Artifact Registry."
}
