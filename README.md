# ZEST Cloud Kubernetes Deployment

This project contains Kubernetes configuration files for deploying the ZEST FIWARE-based interoperability hub to a Kubernetes cluster.

## Project Structure

This is step one of the ZEST cloud platform: the core FIWARE context broker stack. Their _deployment_ and _service_ configurations are stored separately, based on the components, within subdirectories of the _k8s/_ directory.

```
.
├── README.md
├── k8s
│   ├── orion/
│   ├── mongo/
│   ├── quantumleap/
│   ├── cratedb/
│   ├── grafana/
│   ├── dashboard-biopc/   # ZEST dashboard pinned to the BioPC tenant
│   ├── dashboard-dti/     # ZEST dashboard pinned to the DTI tenant
│   ├── postgres/
│   ├── minio/             # S3-compatible object store for experimental dataset files
│   └── zest-data-api/     # experimental-dataset API over postgres + minio (see ../zest-data-api)
├── manage.sh
├── setup-steps.md
└── scripts
    └── send_mock_measurements.py
```

## Architecture

The ZEST interoperability hub is built around the FIWARE Orion Context Broker (NGSI-LD), which acts as the central hub for context information collected from field/industrial partners.

### Key Components and Their Roles

#### 1. Orion Context Broker

Acts as the central message hub for managing contextual information. It receives context updates from data sources (e.g. edge connectors at partner sites) and stores them in MongoDB for persistent storage. It also manages subscriptions that forward updates to downstream consumers such as QuantumLeap.

#### 2. MongoDB

MongoDB is used as the primary database for the Orion Context Broker. It stores all context data and subscription information managed by Orion.

#### 3. QuantumLeap

QuantumLeap subscribes to updates from the Orion Context Broker and stores time-series data in CrateDB, enabling historical queries and analytics over the collected data.

#### 4. CrateDB

CrateDB is a distributed SQL database that serves as the time-series backend for QuantumLeap. It also exposes a PostgreSQL wire-protocol endpoint (port 5432), which Grafana uses to query it directly.

#### 5. Grafana

Grafana provides dashboards over the time-series data QuantumLeap has written to CrateDB. It connects to CrateDB using Grafana's built-in PostgreSQL data source (CrateDB is wire-compatible with PostgreSQL). The data source and a starter dashboard are provisioned automatically from `k8s/grafana/provisioning.yaml` on pod startup, so there's nothing to click through manually to get a first chart.

#### 6. MinIO

An S3-compatible object store (`minio/minio`) that holds the **files** of experimental fermentation
datasets. Deployed as a `ClusterIP` Service `minio` (`:9000` S3 API, `:9001` web console) backed by a
`minio-pvc` PersistentVolumeClaim. `zest-data-api` writes/reads dataset objects here; the web console is
reachable with `kubectl port-forward svc/minio 9001:9001`. Credentials are dev-grade inline env
(`zest` / `zest-minio-dev`) — change before any real deployment.

#### 7. zest-data-api

A FastAPI service (built in the sibling `../zest-data-api` repo) that stores and serves **experimental
fermentation datasets** — a relational flow entirely separate from the Orion → QuantumLeap → CrateDB
time-series pipeline above. Dataset **files** go to **MinIO**; dataset **metadata** and the structured
ZEST data model live in `postgres-db`. It exposes a REST API (generic multi-file upload + list +
download) consumed by the ZEST dashboard's "Datasets" tab. Deployed as a `ClusterIP` Service on `:8091`;
an initContainer runs `alembic upgrade head` against `postgres-db` before the API starts. The image is
`ghcr.io/zest-eu/zest-data-api:latest` (built by that repo's CI).

Deploy (needs `postgres-db` + `minio` running first, and the GHCR image pullable — add a `ghcr-pull`
imagePullSecret if the package is private):

```bash
kubectl apply -f k8s/postgres/        # if not already up
kubectl apply -f k8s/minio/           # object store for dataset files
kubectl apply -f k8s/zest-data-api/
kubectl rollout status deploy/zest-data-api
kubectl port-forward svc/zest-data-api 8091:8091   # then http://localhost:8091/docs
```

### Data Flow

1. A partner's edge connector (e.g. the FIWARE SCADA OPC-UA connector used by DTI) pushes context updates (NGSI-LD entities) to the Orion Context Broker.
2. Orion persists the current state of each entity in MongoDB.
3. Orion notifies QuantumLeap of updates via subscription.
4. QuantumLeap stores the time-series history in CrateDB, available for querying/analytics.
5. Grafana queries CrateDB (via its PostgreSQL endpoint) to visualize the time-series data on dashboards.

### Pilots and Data Producers (planned)

The first data-producing pilot is DTI, whose SCADA system exposes measurement tags via the FIWARE SCADA OPC-UA connector. A client for this pilot will live in the sibling `dti-client` directory, and the tags it collects will be modeled as FIWARE Smart Data Models before being sent to Orion. These are tracked as follow-up steps to this cloud setup.

## Component Descriptions

### Orion Context Broker

The Orion Context Broker (orion-ld) is an implementation of the NGSI-LD API that allows you to manage the entire lifecycle of context information including updates, queries, registrations, and subscriptions.

Key features:
- NGSI-LD compliant API
- Real-time updates and notifications
- Query and subscription capabilities
- JSON-LD data format support

### MongoDB

Key features:
- Document-oriented database
- High performance
- High availability
- Automatic scaling

### QuantumLeap

QuantumLeap is a REST service for storing, querying, and retrieving NGSI v2 and NGSI-LD spatio-temporal data. It acts as a connector between Orion Context Broker and time-series databases (in this case, CrateDB).

Key features:
- Time-series data storage
- Geospatial queries
- Multi-tenancy support
- Integration with various time-series databases

#### Querying QuantumLeap directly

QuantumLeap has no web UI, but its REST API can be queried directly (useful for checking that data actually made it through the pipeline, independent of Grafana/CrateDB). Since our data is ingested without a `Fiware-ServicePath` header, it's stored under the root service path (`/`) — you must pass `Fiware-ServicePath: /` explicitly on queries, or QuantumLeap won't match it and will report no records:

```bash
# Get an entity + full history of its attributes
curl "http://localhost:8668/v2/entities/urn:ngsi-ld:DeviceMeasurement:Temperature:001" \
  -H "Fiware-ServicePath: /"

# List all known entities of a type
curl "http://localhost:8668/v2/entities?type=DeviceMeasurement" \
  -H "Fiware-ServicePath: /"

# History of a single attribute (lastN, fromDate/toDate, hLimit/hOffset also supported)
curl "http://localhost:8668/v2/entities/urn:ngsi-ld:DeviceMeasurement:Temperature:001/attrs/numValue?lastN=20" \
  -H "Fiware-ServicePath: /"
```

### CrateDB

Key features:
- Distributed SQL database
- Real-time analytics
- Time-series data optimization
- Horizontal scalability

### ZEST Dashboard (per tenant)

The React dashboard (built + served by nginx — image
`ghcr.io/zest-eu/data-dashboard`, from the sibling `zest-dashboard` repo) is a
lightweight alternative to Grafana: it lists the live `DeviceMeasurement`
entities from Orion and charts each one's history from QuantumLeap. The nginx
layer also reverse-proxies the browser's `/api/*` calls to Orion/QuantumLeap and
injects the required FIWARE headers.

The tenant a dashboard shows is **fixed per container** (nginx bakes the
`NGSILD-Tenant` header in at startup), so there is **one deployment per tenant**:

| Component | Tenant (`ORION_TENANT`) | External port | URL under `minikube tunnel` |
|---|---|---|---|
| `dashboard-biopc` | `opcua_biopc` | 8080 | http://localhost:8080 |
| `dashboard-dti` | `dti` | 8081 | http://localhost:8081 |

To point at a different tenant, or to add another, copy one of the
`k8s/dashboard-*/` directories and change `ORION_TENANT` (and the Service `port`)
— the image is identical. The image is pulled from GHCR; if the package is
private, create a pull secret and reference it (see the commented block in the
deployment manifests).

> **QuantumLeap caveat:** the dashboard reads history from QuantumLeap's **default**
> tenant (it sends `Fiware-ServicePath: /` and no `Fiware-Service`). That matches how
> this stack currently ingests data, so BioPC/mock charts work. If a tenant's history
> is ever stored under its own `Fiware-Service`, the charts for that tenant will come
> up empty until the dashboard image is extended to send a per-tenant `Fiware-Service`.

### Note on MongoDB version

`fiware/orion-ld` requires MongoDB's wire protocol version 8+ (MongoDB 4.2 or newer) - it will fail to start against older MongoDB (e.g. 3.6, used in some older FIWARE deployment examples) with a `mongocTenantsGet` error. This was confirmed by running the images locally, and `k8s/mongo/deployment.yaml` here is pinned to `mongo:4.4` accordingly.

## Deployment

> **Deploying to GCP/GKE?** See [`setup-steps.md`](setup-steps.md) for a full step-by-step runbook
> (cluster creation, the required GKE manifest tweaks, the standalone Postgres database, and
> verification).

To deploy the components to your Kubernetes cluster, use the _manage.sh_ script provided in the repository:

```bash
./manage.sh start
```

Alternatively, you can spin up all of the pods manually using kubectl like so:

```bash
kubectl apply -f k8s/
```

This will apply all the Kubernetes configuration files in the k8s/ directory and its subdirectories. On startup, Orion will register an NGSI-LD subscription (see `k8s/orion/subscriptions-setup.yaml`) that forwards `DeviceMeasurement` updates to QuantumLeap. This is a starting point based on the generic FIWARE Device Smart Data Model — it should be revisited once the DTI tag list is mapped to concrete Smart Data Models.

Grafana (LoadBalancer, port 3000) comes up with its CrateDB datasource and a starter dashboard already provisioned — log in at `admin` / `admin` and the "Device Measurements" dashboard is ready to go, no manual data source setup needed.

Two ZEST Dashboard instances also come up as LoadBalancer services — `dashboard-biopc` (port 8080, tenant `opcua_biopc`) and `dashboard-dti` (port 8081, tenant `dti`). See [ZEST Dashboard (per tenant)](#zest-dashboard-per-tenant) for details. The `dashboard-dti` instance will simply show no data until the DTI connector feeds the `dti` tenant.

### Mock data

To see the dashboard populated without a real edge connector, use `scripts/send_mock_measurements.py` (Python 3, standard library only). It creates two `DeviceMeasurement` entities in Orion (a flow rate and a temperature sensor) and updates each one repeatedly to build up a short time series:

```bash
python3 scripts/send_mock_measurements.py
# or, if Orion isn't at the default http://localhost:1026:
python3 scripts/send_mock_measurements.py --orion-url http://localhost:1026 --points 50 --interval 0.5
```

Requires a working `minikube tunnel` (or equivalent) so `orion`'s LoadBalancer service is reachable on the host.

To stop all of the components, you can run the same _manage.sh_ script with the "stop" argument:

```bash
./manage.sh stop
```

### NOTE: Local development

When running the cluster locally, if using _minikube_, a tunnel must be opened to allow external access to LoadBalancer services (Orion, QuantumLeap). This can be done via _minikube_ using the following command:

```bash
minikube tunnel
```

If using CrateDB on a Linux host/node, you may also need to raise `vm.max_map_count` (see `k8s/cratedb/vm-max-map-count.yaml`, applied automatically as a DaemonSet).

## Configuration

Each component may have specific configuration options. Refer to the individual YAML files for detailed configuration settings.

## Prerequisites

* Kubernetes cluster

* kubectl configured to communicate with your cluster

* Required images pulled and accessible to your cluster

## Monitoring and Logging

Refer to your Kubernetes cluster's monitoring and logging solutions for observing the deployed components.

## Roadmap

This repository currently covers the cloud/context-broker side only. Planned follow-ups:

- `dti-client`: a client using the FIWARE SCADA OPC-UA connector to collect measurement tags from DTI's SCADA system and forward them to Orion.
- Smart Data Model definitions for the collected tags, and a corresponding update to the Grafana provisioning (`k8s/grafana/provisioning.yaml`) and QuantumLeap subscription (`k8s/orion/subscriptions-setup.yaml`) to match the concrete entity types/attributes.
- Access control / gateway (e.g. Keycloak + OAuth2 proxy) in front of Orion/QuantumLeap/Grafana, once the hub is exposed beyond trusted networks.
- Persistent storage for Grafana if dashboards need to be authored/edited through the UI rather than provisioned as code.
