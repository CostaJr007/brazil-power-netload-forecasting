# Tests

All tests run offline with pytest (91 tests), including the collector, the Silver contracts, the Gold views and the models.

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
```

- **Collector:** reuse of identical content, preservation of revisions, rejection of HTML or oversized responses, no half-written files and correct resource selection. `TemporaryDirectory` isolates files and `patch.object` replaces the network with in-memory responses.
- **Leakage tests:** the future is overwritten with extreme values and the forecast must not change (models, bias corrections, prediction band).
- **Data cleaning and operations:** night-time solar, frozen values, effective horizon choice and the net-load sum across subsystems.

The tests do not certify that ONS endpoints are available today; that question is answered by the endpoint audit, which uses the network and keeps its own evidence.
