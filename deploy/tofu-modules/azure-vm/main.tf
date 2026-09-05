# Module Azure — monter et détruire une VM derrière le contrat (ticket 10).
#
# Un resource group PAR machine : la destruction est la suppression du RG, et
# l'ordre inverse des dépendances (VM → NIC → NSG → subnet → vnet → RG) est
# exactement ce que le graphe tofu ordonnance seul — l'argument concret du
# state IaC relevé au spike (ticket 3).
#
# ZÉRO exposition : pas d'IP publique, NSG entrant fermé. La machine rejoint le
# tailnet PENDANT SON BOOTSTRAP (cloud-init) — sur Azure, contrairement à
# Proxmox, le portail ne peut pas la joindre autrement pour la configurer
# (réponse à la question 6 du spike, motivation du ticket 7).
#
# Credentials : ARM_CLIENT_ID / ARM_CLIENT_SECRET / ARM_TENANT_ID /
# ARM_SUBSCRIPTION_ID en environnement du process tofu — jamais ici.

terraform {
  backend "pg" {}
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
}

# ─── Entrées — la MachineSpec, traduite en variables ─────────────────────────

variable "name" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$", var.name))
    error_message = "Nom DNS-safe attendu (^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$)."
  }
}
variable "disk_gb" { type = number }
variable "user" { type = string }
variable "ssh_authorized_keys" { type = list(string) }

# ─── Entrées — la section provider ───────────────────────────────────────────

variable "region" { type = string }
# Résolu par le driver depuis la demande cpu/memory_mb (plus petit SKU
# suffisant d'une famille déclarée) — le tranchage du spike, appliqué.
variable "instance_size" { type = string }
variable "resource_group" {
  type    = string
  default = ""
}
# Référence marketplace "publisher:offer:sku:version".
variable "image" {
  type    = string
  default = "Debian:debian-12:12-gen2:latest"
}
variable "subnet_cidr" {
  type    = string
  default = "10.42.0.0/24"
}
# Clé d'enrôlement tailnet À USAGE UNIQUE (ticket 7), consommée par cloud-init
# au premier boot. Sensible : ne sort ni en output ni en log ; elle transite
# par le user-data (métadonnée de la VM) et le state — tous deux morts après
# le premier usage de la clé, et le state est chiffré (ticket 8).
variable "tailnet_authkey" {
  type      = string
  sensitive = true
}
# Tags d'ownership (ticket 11) : qui a créé la machine, pour qui, depuis où.
variable "owner_tags" {
  type    = map(string)
  default = {}
}

locals {
  rg_name = var.resource_group != "" ? var.resource_group : "rg-${var.name}"
  image   = split(":", var.image)
  # Ownership (ticket 11) : posé À LA CRÉATION sur chaque ressource, sans
  # exception — après coup, une ressource sans tag est indiscernable d'une
  # ressource légitime et personne n'ose la supprimer. `owner_tags` complète
  # avec owner=<login> et created-at, composés par l'appelant.
  tags = merge({
    managed-by = "devflow"
    machine    = var.name
  }, var.owner_tags)
  # cloud-init : rejoindre le tailnet au premier boot. Échec = pas de repli
  # silencieux : la machine reste injoignable et le driver échoue sur timeout
  # d'attente tailnet, en échec APRÈS création (le RG existe).
  user_data = <<-CLOUDINIT
    #cloud-config
    runcmd:
      - ['sh', '-c', 'curl -fsSL https://tailscale.com/install.sh | sh']
      - ['tailscale', 'up', '--auth-key=${var.tailnet_authkey}', '--hostname=${var.name}']
  CLOUDINIT
}

# ─── Le graphe — un RG par machine, destruction en cascade ───────────────────

resource "azurerm_resource_group" "machine" {
  name     = local.rg_name
  location = var.region
  tags     = local.tags
}

resource "azurerm_virtual_network" "machine" {
  name                = "vnet-${var.name}"
  location            = azurerm_resource_group.machine.location
  resource_group_name = azurerm_resource_group.machine.name
  address_space       = [var.subnet_cidr]
  tags                = local.tags
}

resource "azurerm_subnet" "machine" {
  name                 = "snet-${var.name}"
  resource_group_name  = azurerm_resource_group.machine.name
  virtual_network_name = azurerm_virtual_network.machine.name
  address_prefixes     = [var.subnet_cidr]
}

# NSG sans règle entrante : les défauts Azure refusent déjà l'entrant Internet,
# le groupe rend le refus EXPLICITE et auditable. Le tailnet passe en sortant.
resource "azurerm_network_security_group" "machine" {
  name                = "nsg-${var.name}"
  location            = azurerm_resource_group.machine.location
  resource_group_name = azurerm_resource_group.machine.name
  tags                = local.tags
}

resource "azurerm_subnet_network_security_group_association" "machine" {
  subnet_id                 = azurerm_subnet.machine.id
  network_security_group_id = azurerm_network_security_group.machine.id
}

resource "azurerm_network_interface" "machine" {
  name                = "nic-${var.name}"
  location            = azurerm_resource_group.machine.location
  resource_group_name = azurerm_resource_group.machine.name
  tags                = local.tags

  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.machine.id
    private_ip_address_allocation = "Dynamic"
    # PAS d'IP publique : la machine n'est joignable que par le tailnet.
  }
}

resource "azurerm_linux_virtual_machine" "machine" {
  name                = var.name
  location            = azurerm_resource_group.machine.location
  resource_group_name = azurerm_resource_group.machine.name
  size                = var.instance_size
  admin_username      = var.user
  tags                = local.tags

  network_interface_ids = [azurerm_network_interface.machine.id]

  dynamic "admin_ssh_key" {
    for_each = var.ssh_authorized_keys
    content {
      username   = var.user
      public_key = admin_ssh_key.value
    }
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = var.disk_gb
  }

  source_image_reference {
    publisher = local.image[0]
    offer     = local.image[1]
    sku       = local.image[2]
    version   = local.image[3]
  }

  custom_data = base64encode(local.user_data)
}

# ─── Sorties ──────────────────────────────────────────────────────────────────

output "resource_group" {
  value = azurerm_resource_group.machine.name
}

output "private_ip" {
  value = azurerm_network_interface.machine.private_ip_address
}

output "vm_id" {
  value = azurerm_linux_virtual_machine.machine.id
}
