# Guide: task_track_classic_website_article_pids

## Purpose

The task `proc.tasks.task_track_classic_website_article_pids` compares the article
PIDs registered in the classic SciELO website (read from a text file listed in
`ClassicWebsiteConfiguration.pid_list_path`) with the `ArticleProc` records already
stored in the system. It then updates each record's `pid_status` field:

| Status | Meaning |
|---|---|
| **matched** | The PID exists in both the classic website and in `ArticleProc` with linked `migrated_data`. |
| **missing** | The PID exists in `ArticleProc` but has no linked `migrated_data`. |
| **exceeding** | The PID is present in `ArticleProc` but was not found in the classic website PID list. |

New PIDs found in the classic website file that do not yet have a corresponding
`ArticleProc` record are automatically created with status **missing**.

### Prerequisites

| Requirement | Details |
|---|---|
| **Classic Website Configuration** | A `ClassicWebsiteConfiguration` record must exist for the target collection, with a valid `pid_list_path` pointing to a text file containing one PID per line. |
| **Collection** | At least one `Collection` record must exist. |
| **User** | A valid Django user (by `username` or `user_id`). |

---

## How to create the periodic task (django_celery_beat)

### Step 1 – Access the administration panel

1. Log in to the Wagtail admin panel (e.g. `https://<your-domain>/admin/`).
2. In the left sidebar menu, go to **Settings > Periodic tasks**.

> If you do not see this menu item, make sure the `django_celery_beat` app is
> installed and that your user has the appropriate permissions.

### Step 2 – Create a new Periodic Task

1. Click **Add periodic task**.
2. Fill in the required fields:

| Field | Value |
|---|---|
| **Name** | A descriptive name, e.g. `Track Classic Website PIDs (scl)` |
| **Task (registered)** | Select `proc.tasks.task_track_classic_website_article_pids` |
| **Enabled** | ✅ Checked |

3. Choose a schedule. For example, to run once a day, create or select an
   **Interval Schedule** of `1 day` or a **Crontab Schedule** such as
   `0 3 * * *` (every day at 03:00).

### Step 3 – Configure the Keyword Arguments (kwargs)

In the **Keyword arguments (JSON)** field, enter a JSON object with the
parameters the task accepts:

```json
{
  "username": "admin",
  "collection_acron": "scl"
}
```

#### Available parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `username` | string | **yes** | Username of the Django user that will be recorded as the creator of any new `ArticleProc` records. |
| `user_id` | integer | no | Alternative to `username`. If both are provided, `user_id` takes precedence. |
| `collection_acron` | string | no | Acronym of the collection to process (e.g. `"scl"` for Brazil). If omitted, **all** collections are processed. |

> **⚠️ Critical:** The `username` or `user_id` must correspond to an existing user.
> If the user is not found, the task will log an error and skip processing.

> **⚠️ Critical:** A `ClassicWebsiteConfiguration` record with a valid
> `pid_list_path` must exist for the target collection. If the configuration
> is missing or the file cannot be read, the task will fail for that
> collection.

### Step 4 – Save

Click **Save**. The task will be picked up by the Celery Beat scheduler
according to the schedule you configured.

---

## Verifying the result

### 1. Task Tracker (Wagtail admin)

In the Wagtail admin sidebar, go to **Task Tracker** (under the Tracker section).
Look for entries with the name
`proc.tasks.task_track_classic_website_article_pids`. Each entry shows:

- **Item** – The collection acronym processed (or `all`).
- **Status** – `started`, `completed`, or `failed`.
- **Detail** – A JSON object containing:
  - `params`: the kwargs used.
  - `events`: a list with the PID status counts per collection (e.g.
    `{"collection": "scl", "matched": 1200, "missing": 50, "exceeding": 3}`).
  - `exceptions`: any errors that occurred.

### 2. ArticleProc records (Wagtail admin)

Navigate to the **ArticleProc** listing in the admin panel and filter by
`pid_status` to verify the distribution:

- **matched** – articles successfully linked.
- **missing** – articles that need attention (no `migrated_data`).
- **exceeding** – articles in the system but not in the classic website PID list.

### 3. Django shell / programmatic check

```python
from proc.models import ArticleProc
from django.db.models import Count

# Summary of pid_status for a collection
ArticleProc.objects.filter(
    collection__acron="scl"
).values("pid_status").annotate(total=Count("pid")).order_by("pid_status")
```

### 4. Celery worker logs

Check the Celery worker output for INFO and ERROR messages related to
`task_track_classic_website_article_pids`. Errors are also recorded in the
`UnexpectedEvent` model, accessible from the Wagtail admin panel.
