"""Tests for deterministic diff rule scanner."""

from shared.cursor_cli.diff_rule_scanner import merge_review_with_diff_scan, scan_diff_for_review

_SAMPLE_DIFF = """
### src/AppCore/AppServices/Vendors/Commands/ScheduledOrder/ScheduledOrderCommandHandler.cs
@@ -0,0 +1,25 @@
+using Dizi.AppCore.Shared.Base;
+using Dizi.AppCore.Shared.ScheduledOrder;
+namespace Dizi.AppCore.AppServices.Vendors.Commands.ScheduledOrder;
+
+public class ScheduledOrderCommandHandler(IVendorCommandRepository vendorCommandRepository) : IRequestHandler<ScheduledOrderCommand, CommandResult<bool>>
+{
+    public async Task<CommandResult<bool>> Handle(ScheduledOrderCommand request, CancellationToken cancellationToken)
+    {
+        return CommandResult<bool>.Success(true);
+    }
+}

### src/AppCore/Shared/ScheduledOrder/ScheduledOrderCommand.cs
@@ -0,0 +1,15 @@
+using Dizi.AppCore.Shared.Base;
+namespace Dizi.AppCore.Shared.ScheduledOrder;
+public class ScheduledOrderCommand : IRequest<CommandResult<bool>>
+{
+    public int VendorId { get; set; }
+}
"""


def test_scan_detects_rr012_rr013_and_suggestions():
    result = scan_diff_for_review(_SAMPLE_DIFF)
    assert result["approved"] is False
    joined = "\n".join(result["findings"])
    assert "[ERROR]" in joined
    assert "RR-012" in joined
    assert "ScheduledOrderCommandHandler.cs:1" in joined
    assert "RR-013" in joined
    assert "CommandValidator" in joined
    assert result["suggestions"]
    assert any("[SUGGESTION]" in s for s in result["suggestions"])


def test_scan_passes_clean_namespace_first_file():
    diff = """
### src/AppCore/Domain/Foo.cs
@@ -0,0 +1,3 @@
+namespace Dizi.AppCore.Domain;
+public class Foo {}
"""
    result = scan_diff_for_review(diff)
    assert result["findings"] == []


def test_merge_prefers_scanner_when_cli_empty():
    parsed = {
        "approved": True,
        "summary": "",
        "findings": [],
        "suggestions": [],
    }
    merged = merge_review_with_diff_scan(parsed, _SAMPLE_DIFF)
    assert merged["approved"] is False
    assert any("RR-012" in f for f in merged["findings"])
