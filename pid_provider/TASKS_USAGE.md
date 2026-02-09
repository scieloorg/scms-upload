# PID Provider Tasks - Usage Examples

## Overview
These tasks allow loading XML documents from the SciELO OPAC API (counter_dict endpoint) 
into the PidProviderXML model without creating Article records.

## Tasks

### 1. task_load_records_from_counter_dict
Orchestrator task that dispatches collection-level tasks.

**Usage:**
```python
from pid_provider.tasks import task_load_records_from_counter_dict

# Load records from Brazil collection
task_load_records_from_counter_dict.delay(
    username="admin",
    collection_acron_list=["scl"],
    from_date="2024-01-01",
    until_date="2024-12-31",
    limit=100,
    timeout=5,
    force_update=False
)
```

**Parameters:**
- `username` (str, optional): Username of the user executing the task
- `user_id` (int, optional): User ID (alternative to username)
- `collection_acron_list` (list, optional): List of collection acronyms. Default: ["scl"]
- `from_date` (str, optional): Start date in ISO format (YYYY-MM-DD)
- `until_date` (str, optional): End date in ISO format (YYYY-MM-DD)
- `limit` (int, optional): Number of documents per page
- `timeout` (int, optional): HTTP request timeout in seconds
- `force_update` (bool, optional): Force update even if record exists
- `opac_domain` (str, optional): OPAC domain. Default: "www.scielo.br"

### 2. task_load_records_from_collection_endpoint
Processes a specific collection using the OPAC harvester.

**Usage:**
```python
from pid_provider.tasks import task_load_records_from_collection_endpoint

# Load records from a specific collection
task_load_records_from_collection_endpoint.delay(
    username="admin",
    collection_acron="scl",
    from_date="2024-01-01",
    until_date="2024-12-31"
)
```

### 3. task_load_record_from_xml_url
Loads an individual document from XML URL into PidProviderXML.

**Usage:**
```python
from pid_provider.tasks import task_load_record_from_xml_url

# Load a single document
task_load_record_from_xml_url.delay(
    username="admin",
    collection_acron="scl",
    pid_v3="ABC123DEF456GHI789",
    xml_url="https://www.scielo.br/j/journal/a/ABC123DEF456GHI789/?format=xml",
    origin_date="2024-01-15",
    force_update=False
)
```

## Important Notes

1. **No Article Creation**: Unlike similar tasks in the core repository, these tasks 
   **only create/update PidProviderXML records**. They do NOT create Article records.

2. **Error Handling**: All errors are logged using the `UnexpectedEvent` model for 
   proper tracking and debugging.

3. **Asynchronous Execution**: These are Celery tasks and execute asynchronously. 
   Check the Celery worker logs for execution status.

4. **OPAC API**: The harvester uses the `/api/v1/counter_dict` endpoint from the 
   new SciELO website to collect document metadata.

## Example: Full Workflow

```python
# 1. Start the orchestrator task for Brazil collection
task_id = task_load_records_from_counter_dict.delay(
    username="admin",
    collection_acron_list=["scl"],
    from_date="2024-01-01",
    until_date="2024-12-31",
    limit=50  # Process 50 documents per page
)

# 2. Monitor Celery logs to track progress
# The orchestrator will dispatch:
# - task_load_records_from_collection_endpoint for each collection
# - task_load_record_from_xml_url for each document found

# 3. Check PidProviderXML model for loaded records
from pid_provider.models import PidProviderXML
recent_records = PidProviderXML.objects.filter(
    created__gte="2024-01-01"
).order_by("-created")[:10]
```

## Monitoring

Monitor task execution through:
1. Celery worker logs: Check for INFO/ERROR messages
2. UnexpectedEvent model: Query for any errors during execution
3. PidProviderXML model: Verify records were created/updated

```python
# Check for errors
from tracker.models import UnexpectedEvent
recent_errors = UnexpectedEvent.objects.filter(
    detail__task__in=[
        "task_load_records_from_counter_dict",
        "task_load_records_from_collection_endpoint", 
        "task_load_record_from_xml_url"
    ]
).order_by("-created")[:10]
```
