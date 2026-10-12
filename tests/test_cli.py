import shutil

from fleetaudit import cli


def test_audit_writes_reports(data_dir, tmp_path, capsys):
    out = tmp_path / "reports"
    assert cli.main(["audit", "--data", str(data_dir / "book"), "--out", str(out)]) == 0
    for f in ("findings.md", "findings.csv", "dealer_scorecard.csv", "approver_scorecard.csv",
              "rule_exposure.png", "dealer_watchlist.png"):
        assert (out / f).stat().st_size > 0, f
    assert "DQ passed" in capsys.readouterr().out


def test_contract_explains_itself(data_dir, truth, capsys):
    cid = truth["contracts"]["duplicate_vin"][0]
    assert cli.main(["contract", cid, "--data", str(data_dir / "book")]) == 0
    out = capsys.readouterr().out
    assert cid in out and "already on" in out


def test_broken_data_fails_the_gate(data_dir, tmp_path, capsys):
    bad = tmp_path / "bad"
    shutil.copytree(data_dir / "book", bad)
    lines = (bad / "payments.csv").read_text(encoding="utf-8").splitlines()
    header, first = lines[0], lines[1].split(",")
    first[3] = str(float(first[3]) + 100)          # amount_due no longer matches the contract
    (bad / "payments.csv").write_text("\n".join([header, ",".join(first)] + lines[2:]) + "\n", encoding="utf-8")
    assert cli.main(["audit", "--data", str(bad), "--out", str(tmp_path / "r")]) == 2
    assert "payment_amount_due_mismatch" in capsys.readouterr().out
