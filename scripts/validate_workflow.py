from pathlib import Path

import yaml

workflow_path = Path(__file__).parents[1] / ".github" / "workflows" / "docker-build.yml"
with workflow_path.open("r", encoding="utf-8") as workflow_file:
    workflow = yaml.safe_load(workflow_file)

assert workflow["name"] == "Build and Push Docker Image"
assert workflow[True]["push"]["branches"] == ["main", "master"]
job = workflow["jobs"]["build-and-push"]
assert job["runs-on"] == "ubuntu-latest"
assert job["steps"][-1]["uses"] == "docker/build-push-action@v6"
assert job["steps"][-1]["with"]["context"] == "./app"
assert job["steps"][-1]["with"]["push"] is True
print("GitHub Actions workflow YAML is valid")
