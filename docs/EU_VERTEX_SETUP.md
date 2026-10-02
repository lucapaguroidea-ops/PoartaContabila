# EU route for document reading: Gemini on Vertex AI in an EU region

**Status:** draft, not configured. This is the owner's setup guide of 2026-10-02, reviewed and
corrected (§0 lists what changed). Nothing here applies to synthetic tests, which keep the
OpenRouter route.

**Blocked by** (all four must be cleared before the first client document):

1. **Owner decision: the EU route per model family.** `00_LAW.md` §3 invariant 5 names Scaleway
   as the EU host. Scaleway's hosted models do not include Gemini, so Gemini document reading on
   Vertex AI EU is a second EU route. The law needs the owner's change first, e.g.:
   - document reading: Vertex AI EU (this guide);
   - System Two (DeepSeek / GLM): Scaleway;
   - System One (Jev): open, because where Jev processes data is unknown.
2. **A domain the owner controls**, for the Google Cloud organization (§A).
3. **The live sender** (WP-20 / WP-24): Poarta sends nothing to any model yet.
4. **Leaving synthetic data**, together with the client-side paperwork in §D.

`[verify]` marks a point to check in Google's or Railway's current documentation while doing the
step. Console menu names move; on 2026-10 Google's docs show Vertex AI under the name "Gemini
Enterprise Agent Platform".

---

## 0. What the review changed

| Source guide said | Correction |
|---|---|
| Using OpenRouter "creates structural compliance failure under GDPR and the EU AI Act" | Overstated. GDPR does not require EU-only processing. It requires a lawful basis, an Art. 28 processor contract with every processor in the chain, and a lawful transfer mechanism for any processing outside the EU. The AI Act sets no data-residency rule; what applies here is AI literacy (Art. 4) and transparency duties. Keeping client data in the EU with a direct Google contract is still the simplest defensible design, because it removes OpenRouter (US) from the chain. |
| Railway region `fra1` (Frankfurt) | Railway has no Frankfurt region. Its EU region is **Europe West, `europe-west4-drams3a` (Amsterdam, NL)**. `PoartaContabila` and `poarta-postgres` already run there (checked 2026-10-02). |
| Selecting the Railway region "guarantees data-in-transit never routes outside the EU" | False. Railway terminates TLS at the **edge location nearest the caller**, which can be outside the EU, before routing to the region. Keep Poarta's model calls off public URLs (§G). |
| Org policy `in:eu-locations` "denies any … execution request" outside the EU | `constraints/gcp.resourceLocations` controls where **resources are created**. It does not by itself pin where each Gemini request is processed. That comes from always calling an **EU regional endpoint**: never the `global` endpoint, never an API key (§E). |
| Console steps: "Applies to: Customize", "Value Type: In" | The current editor reads: *Manage policy → Override parent's policy → Add a rule → Policy values: Custom → Policy type: Allow → Custom value* `in:eu-locations`. |
| The super admin can edit organization policies | No. Organization policies need **Organization Policy Administrator** (`roles/orgpolicy.policyAdmin`), which a super admin or Organization Administrator does not hold by default. Grant it first (§B.1). |
| Create a JSON service-account key | Organizations created on or after **3 May 2024** enforce `iam.disableServiceAccountKeyCreation` by default ("secure by default"), so the step fails as written. §C.6 gives the controlled exception, an expiry and rotation. |
| Nothing on data retention | Vertex AI **caches Gemini inputs in memory for up to 24 h** by default, and may **log prompts for abuse monitoring** unless the project is on invoiced billing or has an exception. Zero data retention needs both turned off, and no grounding with Google Search (§D). |
| Proxy code with `vertexai.generative_models` (`google-cloud-aiplatform==1.44.0`) | That module was deprecated on 24 June 2025 with removal announced for 24 June 2026. Use the **Google Gen AI SDK** (`google-genai`) with `vertexai=True` and an EU `location` (§E). |
| Proxy accepts any `Authorization` header; client uses `api_key="any-placeholder"` | An **open relay** to a billed Vertex project on a public URL. Not acceptable (§F). |
| Proxy maps any model name containing "flash" to one model, else to another | A silent model swap, against `00_LAW.md` invariant 5 (one exact model per role, no aliases). |
| Proxy forwards only the last message, as text | It drops the role card (system message), the history and the PDF or image. Document reading cannot work through it. |
| Writes the credentials JSON to a file in the working directory | Load the key from the variable into memory; never write it to disk (§E). |
| Footer "For medical advice … consult a professional" | Text from a generator, removed. |

---

## 1. Where this fits Poarta

Poarta controls its own code, so it needs **no OpenRouter-compatible proxy**. The EU route is a
transport inside Poarta, chosen per role:

- `ARTICOLE_MODEL_ROLES_v1.yaml`: each document-reading role (`ocr_extract`,
  `ocr_decont_split`) gets an `eu_route` in the checked shape of WP-35:

  ```yaml
  eu_route:
    provider: vertex
    location: europe-west4
    model: <exact Vertex model id>
    key_env: GCP_DOCREAD_SA_JSON
    project_env: GCP_DOCREAD_PROJECT
  ```

  A non-EU region, `global` or an alias does not load.
- `model_roles.route_check`: a tenant with `data_class: client` goes only to `eu_route`, and a
  role without one refuses. This rule already exists.
- The live sender (blocked, item 3) gets one Vertex transport beside the OpenRouter one.
- What is recorded under `MODEL_CALLS=dry` stays the same, so the shadow and smoke runs
  (WP-26, WP-29) show the route before anything is sent.

A separate proxy service (§F) is only worth it for a third-party tool that can speak nothing
but the OpenAI / OpenRouter format.

---

## A. Google Cloud organization (Cloud Identity Free)

A plain `@gmail.com` account has no organization, so no organization policies. Use Cloud
Identity Free on a domain you control.

1. Sign up at <https://workspace.google.com/signup/gcpidentity/welcome> and choose "I have a
   domain".
2. Create the admin account, e.g. `admin@<your-domain>`. Use it only for administration; set a
   recovery email.
3. Verify the domain with the DNS `TXT` record Google gives you.
4. Turn on **2-step verification** for the admin, ideally a security key, and enforce it for the
   organization: Admin console → Security → 2-step verification.
5. Sign in to <https://console.cloud.google.com> as the admin and accept the terms. The
   **organization resource** is created then. Note its numeric ID.

## B. Organization policies

1. **Grant yourself the policy roles.** IAM & Admin → IAM, with the organization selected →
   grant the admin `Organization Administrator` and `Organization Policy Administrator`. CLI
   equivalent:
   `gcloud organizations add-iam-policy-binding ORG_ID --member=user:admin@<domain> --role=roles/orgpolicy.policyAdmin`
2. **Resource locations.** IAM & Admin → Organization policies → `gcp.resourceLocations`
   ("Google Cloud Platform – Resource Location Restriction"):
   - Manage policy → Override parent's policy → Add a rule;
   - Policy values: **Custom** → Policy type: **Allow** → value `in:eu-locations` → Done → Set
     policy.

   Allow time to propagate (Google states up to about 15 minutes `[verify]`). This keeps
   buckets, datasets and other stored resources in the EU. It does not route requests (§E).
3. **Keep the secure-by-default policies on.** Check they are enforced:
   - `iam.disableServiceAccountKeyCreation`;
   - `iam.allowedPolicyMemberDomains` (only your domain can be granted access);
   - `iam.automaticIamGrantsForDefaultServiceAccounts`;
   - `storage.uniformBucketLevelAccess`.
4. Optional hygiene: remove the domain-wide **Project Creator** and **Billing Account Creator**
   grants that a new organization gives every user.

## C. Project, billing, API, service account

1. **Project:** create one under the organization, e.g. `poarta-eu-docread`.
2. **Billing:** link a billing account.
   - Put the company's legal details on the billing profile.
   - Set a **budget with alerts**, e.g. at 50 / 90 / 100 % of a monthly cap.
   - **Invoiced billing** matters for zero data retention (§D.2); ask Google whether the company
     qualifies `[verify]`.
3. **API:** enable the **Vertex AI API** (`aiplatform.googleapis.com`) on this project only.
4. **Region and model:** pick one EU region and one exact model id.
   - Check Vertex AI's *Locations* and *Data residency* pages that the model is offered on that
     **regional** endpoint, with **ML processing in the region** `[verify]`.
   - New Gemini models sometimes launch on the `global` endpoint first. Such a model is not
     usable here until it has an EU regional endpoint.
   - `europe-west4` (Netherlands) sits in the same country as Railway's EU region.
     `europe-west3` (Frankfurt) works too if the model is offered there.
5. **Service account:** create `vertex-docread`.
   - Grant **Vertex AI User** (`roles/aiplatform.user`) on this project only. A custom role
     holding just the predict permissions is narrower `[verify the permission names]`.
   - Grant nothing at the organization level.
6. **The key.** Railway offers no workload identity federation to Google, so a key is the
   practical choice. Because of B.3, do it as a controlled exception:
   1. On **this project only**, override `iam.disableServiceAccountKeyCreation` to not enforced.
   2. Set `iam.serviceAccountKeyExpiryHours` on the project, e.g. 2160 h (90 days) `[verify the
      allowed values]`.
   3. Service account → Keys → Add key → JSON. The file downloads once.
   4. Restore the enforcement at once. Existing keys keep working; no new ones can be made.
   5. Put the JSON straight into Railway as a **sealed** variable (§G), then delete the
      downloaded file. Never commit it, email it, or paste it into a chat.
   6. Rotate before expiry by repeating 1–5 and deleting the old key.
7. **Audit logs:** Cloud Audit Logs record admin activity by default. Data Access logs for Vertex
   AI are optional; if enabled, they must not store the prompts `[verify]`.

## D. Data protection settings

1. **Training:** Google Cloud's terms bar Google from training its models on customer data sent
   to Vertex AI. This is the main difference from the AI Studio free tier, which is for
   synthetic data only.
2. **Zero data retention** (Vertex AI's "zero data retention" page `[verify current steps]`):
   - **Turn off in-memory caching** for the project. It is on by default and keeps Gemini inputs
     up to 24 h in the serving region. It is switched off with an API call at project level.
   - **Abuse-monitoring prompt logging:** it does not apply to invoiced-billing accounts; others
     request an exception through Google's form.
   - **Never enable grounding with Google Search** on these roles; it keeps data longer.
3. **Contract and records** (the accounting practice is the processor for its clients; Google
   becomes a sub-processor):
   - The **Cloud Data Processing Addendum** is part of the Google Cloud terms. In the console's
     Privacy & Security page, enter the company's DPO / privacy contact `[verify]`.
   - **Client contracts** must allow sub-processors (GDPR Art. 28(2) and (4)). Name Google Cloud
     (Vertex AI, EU region) and Railway, and give clients notice of changes.
   - Add both to the **record of processing** (Art. 30). Decide with the DPO or adviser whether
     a **DPIA** (Art. 35) is needed for AI processing of clients' financial documents.
   - Check that professional secrecy duties allow this sub-processing, and record that check.

## E. Calling Vertex AI from Poarta (the transport, once the sender is unblocked)

Requirements:

- **Library:** use `google-genai`, not `vertexai.generative_models`. Add it as a pinned
  dependency in `pyproject.toml` / `uv.lock`.
- **Authentication:** use the service account only. An **API key** sends requests to the global
  endpoint and gives no residency guarantee.
- **Location:** set it in code from the role's `eu_route`, never from a request. Never use
  `global`.
- **Model:** the role's exact model id; unknown ids refuse.
- **What is sent:** the role card as the system instruction and the document as a file part.
  Bytes go only to this route and only for `data_class: client`.
- **Credentials:** load them from the sealed variable into memory, never write them to disk.
- **Logs:** never log prompts, documents or answers. Record hashes, as `/model-calls` does.

```python
import json, os
from google import genai
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_info(
    json.loads(os.environ["GCP_DOCREAD_SA_JSON"]),
    scopes=["https://www.googleapis.com/auth/cloud-platform"],
)
client = genai.Client(
    vertexai=True,
    project=os.environ["GCP_DOCREAD_PROJECT"],
    location="europe-west4",  # from the role's eu_route; never "global"
    credentials=creds,
)
```

Variables (names proposed; they join `ARCHITECTURE.md` §14 with the transport):
`GCP_DOCREAD_PROJECT`, `GCP_DOCREAD_SA_JSON` (sealed).

## F. If a separate proxy is ever needed

Only for a tool that cannot be changed. It must:

- run in Railway's EU region with **no public domain**, reachable only on private networking
  (`<service>.railway.internal`);
- check a **real secret** with a constant-time compare (`hmac.compare_digest`), not just that a
  header is there;
- map model names through an **explicit allow-list**, refusing anything unknown (no substring
  matching);
- forward the system message, every message, and file / image parts, or refuse what it cannot
  forward;
- use the async client or a sync route, so one call does not block the server;
- meet every requirement in §E.

## G. Railway side

- **Region:** confirmed 2026-10-02 that `PoartaContabila` and `poarta-postgres` run in
  `europe-west4-drams3a` (Amsterdam).
- **Bucket:** check that `poarta-bucket` was created in the EU region. A bucket's region is
  chosen at creation and cannot be changed.
- **Edge:** public requests to the operator API enter at the caller's nearest edge location, so a
  person uploading from Romania normally lands on an EU edge, but that is not guaranteed. Model
  calls go **out** from the service to Google and do not pass Railway's edge.
- **Secrets:** set `GCP_DOCREAD_SA_JSON` as a **sealed** variable; its value is then hidden in
  the dashboard and API.
- **Contract:** Railway processes client data too (database, bucket, logs). Accept its DPA,
  list it as a sub-processor (§D.3), and check where its logs and backups are kept `[verify]`.

## H. Before the first client document

- [ ] Decision on the EU route recorded in `00_LAW.md`, item 1 above.
- [ ] Organization, policies and project done (§A–§C). `gcloud org-policies describe
      gcp.resourceLocations --organization=ORG_ID` shows `in:eu-locations`.
- [ ] Key created as an exception, enforcement restored, key expiry set, file deleted.
- [ ] Caching turned off, abuse-monitoring exception or invoiced billing confirmed (§D.2).
- [ ] Client contracts, Art. 30 record and DPIA decision done (§D.3).
- [ ] Roles carry `eu_route` and an EU-region model id. The smoke run (`--local`) shows a
      client tenant routed to the EU route and refused everywhere else.
- [ ] One test call with a synthetic document on the EU route. Check the request reached the
      chosen region (Vertex AI request logs or metrics in that region `[verify]`).

## Sources

Checked 2026-10-02. Google's documentation site could not be opened from the build session;
these points come from search results and Railway's own docs.

- Google Cloud, secure-by-default organizations (enforced from 3 May 2024, including
  `iam.disableServiceAccountKeyCreation`):
  <https://docs.cloud.google.com/resource-manager/docs/secure-by-default-organizations>
- Google Cloud, Vertex AI zero data retention (24 h caching; abuse monitoring; invoiced
  billing): <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/vertex-ai-zero-data-retention>
- Google Cloud, Vertex AI SDK migration guide (`vertexai.generative_models` deprecated
  2025-06-24, removal 2026-06-24):
  <https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/deprecations/genai-vertexai-sdk>
- Google Cloud, locations (do not use the global endpoint for ML-processing residency):
  <https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/general/locations>
- Organization Policy Administrator is not held by super admins by default:
  <https://docs.cloud.google.com/resource-manager/docs/access-control-org>
- Railway, edge networking (TLS ends at the nearest edge; four regions, EU = Amsterdam):
  <https://docs.railway.com/networking/edge-networking>
- Railway, sealed variables: <https://docs.railway.com/variables#sealed-variables>
- Railway, storage buckets (region fixed at creation): <https://docs.railway.com/storage-buckets>
