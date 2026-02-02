terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# --- Networks (1 VPC per site) ---

resource "google_compute_network" "vpc_site1" {
  name                   = "vpc-site1"
  auto_create_subnetworks = false
}


# --- Subnets (1 subnet per prefix) ---

resource "google_compute_subnetwork" "subnet_site1_1" {
  name          = "subnet-site1-1"
  region        = var.region
  ip_cidr_range = "192.168.10.0/24"
  network       = google_compute_network.vpc_site1.self_link
}


# --- Instances (VMs) ---

resource "google_compute_instance" "pc01" {
  name         = "pc01"
  machine_type = "e2-micro"
  zone         = var.zone

  tags = ["site-site1", "role-ordinateur"]

  boot_disk {
    initialize_params {
      image = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.subnet_site1_1.self_link
    
    access_config {}
  }

  metadata = {
    "enable-oslogin" = "TRUE"
  }
}

resource "google_compute_instance" "pc02" {
  name         = "pc02"
  machine_type = "e2-micro"
  zone         = var.zone

  tags = ["site-site1", "role-ordinateur"]

  boot_disk {
    initialize_params {
      image = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.subnet_site1_1.self_link
    
    network_ip = "192.168.10.20"
    
    access_config {}
  }

  metadata = {
    "enable-oslogin" = "TRUE"
  }
}


# --- Baseline firewall (SSH always, HTTP/HTTPS optional) ---

resource "google_compute_firewall" "allow_ssh_site1" {
  name    = "allow-ssh-site1"
  network = google_compute_network.vpc_site1.name

  direction = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags = ["site-site1", "role-ordinateur"]

  allow {
    protocol = "tcp"
    
    ports = [tostring(var.ssh_port)]
    
  }
}

resource "google_compute_firewall" "allow_http_site1" {
  name    = "allow-http-site1"
  network = google_compute_network.vpc_site1.name

  direction = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags = ["site-site1", "role-ordinateur"]

  allow {
    protocol = "tcp"
    
    ports = ["80"]
    
  }
}

resource "google_compute_firewall" "allow_https_site1" {
  name    = "allow-https-site1"
  network = google_compute_network.vpc_site1.name

  direction = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags = ["site-site1", "role-ordinateur"]

  allow {
    protocol = "tcp"
    
    ports = ["443"]
    
  }
}


# --- Custom firewall rules from infra_candidate.firewall_rules ---

resource "google_compute_firewall" "fw_1_site1_allow_web" {
  name    = "allow-web-site1"
  network = google_compute_network.vpc_site1.name

  direction = "INGRESS"
  source_ranges = ["192.168.10.0/24"]
  target_tags = ["site-site1", "role-ordinateur"]

  allow {
    protocol = "tcp"
    ports    = ["80"]
  }
}
