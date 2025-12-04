# TUFLOW Model Health QA/QC

Tools for automated pre-run and test-run quality checks for TUFLOW models.

## CLI usage

Resolve a TCF template and list referenced control files plus external inputs:

```bash
python -m tuflow_qaqc.pre_run "T03_B155a_~e1~_~e2~_~s1~.tcf" -e1 00100Y -e2 0060m -s1 5m
```

On Windows PowerShell, use a single line or PowerShell's backtick `` ` `` for
continuation. Backslashes (``\``) do not continue commands in PowerShell:

```powershell
python -m tuflow_qaqc.pre_run "T03_B155a_~e1~_~e2~_~s1~.tcf" -e1 00100Y -e2 0060m -s1 5m
# or multi-line
python -m tuflow_qaqc.pre_run `
  "T03_B155a_~e1~_~e2~_~s1~.tcf" `
  -e1 00100Y `
  -e2 0060m `
  -s1 5m
```

You can also supply wildcards inline (useful on Windows):

```powershell
python -m tuflow_qaqc.pre_run "T03_B155a_~e1~_~e2~_~s1~.tcf" -e1=00100Y -e2=0060m -s1=5m
```
