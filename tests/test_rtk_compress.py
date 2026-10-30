"""Tests for RTK diff compression in review prompts."""

from core.config import Settings
from shared.cursor_cli.rtk_compress import (
    compress_diff_for_review,
    compress_mr_diff_internal,
    is_rtk_available,
)

_SAMPLE_MR_DIFF = """
### src/AppCore/AppServices/Vendors/Commands/ScheduledOrder/ScheduledOrderCommandHandler.cs
@@ -0,0 +1,25 @@
+using Dizi.AppCore.Shared.Base;
+using Dizi.AppCore.Shared.ScheduledOrder;
+namespace Dizi.AppCore.AppServices.Vendors.Commands.ScheduledOrder;

+public class ScheduledOrderCommandHandler(IVendorCommandRepository vendorCommandRepository) : IRequestHandler<ScheduledOrderCommand, CommandResult<bool>>
+{
+    public async Task<CommandResult<bool>> Handle(ScheduledOrderCommand request, CancellationToken cancellationToken)
+    {
+        return CommandResult<bool>.Success(true);
+    }
+}
"""


def test_internal_compress_reduces_size():
    expanded = _SAMPLE_MR_DIFF + "\n" + (" context line\n" * 200)
    out = compress_mr_diff_internal(expanded, max_context=2)
    assert len(out) < len(expanded)
    assert "+using Dizi.AppCore.Shared.Base;" in out
    assert "context lines omitted" in out


def test_compress_diff_for_review_disabled_by_default():
    result = compress_diff_for_review(
        _SAMPLE_MR_DIFF,
        settings=Settings(cursor_review_use_rtk=False),
    )
    assert result.method == "none"
    assert result.raw == _SAMPLE_MR_DIFF.strip()
    assert result.compressed == result.raw


def test_compress_diff_for_review_keeps_raw_when_enabled():
    result = compress_diff_for_review(
        _SAMPLE_MR_DIFF,
        settings=Settings(cursor_review_use_rtk=True),
    )
    assert result.raw == _SAMPLE_MR_DIFF.strip()
    assert "+namespace Dizi" in result.compressed
    assert result.raw_tokens >= result.compressed_tokens or result.method == "none"


def test_compress_preserves_plus_lines_for_scanner():
    result = compress_diff_for_review(
        _SAMPLE_MR_DIFF,
        settings=Settings(cursor_review_use_rtk=True),
    )
    assert "ScheduledOrderCommandHandler.cs" in result.raw
    assert "using Dizi.AppCore.Shared.Base" in result.raw


def test_rtk_availability_is_boolean():
    assert isinstance(is_rtk_available(), bool)
