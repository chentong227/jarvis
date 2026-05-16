from jarvis_blood import PerceptionData
import os

MANIFEST = {"name": "txt_writer_eyes", "description": "感知当前工作目录状态"}

class Eyes:
    def __init__(self):
        pass

    def scan(self, hands=None) -> PerceptionData:
        cwd = os.getcwd()
        return PerceptionData(
            url=f"file://{cwd}",
            page_title="Text Writer Environment",
            interactable_elements=[{"type": "info", "text": f"Current working directory: {cwd}"}]
        )
