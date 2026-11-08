"""Grading: run a task's checks against the live lab and write result.json.

Flow (also the bring-your-own-agent mode):
    stick task start <task>   -> run dir with workspace, canaries, baseline configs, rendered prompt
    <any agent does the work>
    stick grade <run dir>     -> result.json
"""
