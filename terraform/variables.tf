variable "project_id" {
  type        = string
  description = "The Google Cloud Project ID to deploy resources into."
}

variable "region" {
  type        = string
  description = "The GCP region to deploy resources in."
  default     = "us-central1"
}

variable "bucket_name" {
  type        = string
  description = "The name of the GCS bucket to create for document uploads. Must be globally unique."
}

variable "dataset_id" {
  type        = string
  description = "The BigQuery dataset ID to create."
  default     = "document_pipeline"
}

variable "table_id" {
  type        = string
  description = "The BigQuery table ID to create."
  default     = "metadata"
}
