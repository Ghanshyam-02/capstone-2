# Jenkins for the secondary build path, with what our pipeline needs:
# Python (tests, security checks) and the Docker CLI (build the image).
#   docker build -t settlement-jenkins day2/jenkins
FROM jenkins/jenkins:lts-jdk17

USER root
RUN (apt-get update || true) \
 && apt-get install -y --no-install-recommends python3 python3-venv docker-cli \
 && rm -rf /var/lib/apt/lists/*

USER jenkins
# Plugins: pipelines (Jenkinsfile), Git checkout, test reports
RUN jenkins-plugin-cli --plugins workflow-aggregator git junit
# Local learning setup: skip the first-run wizard (no login on http://localhost:8081)
ENV JAVA_OPTS=-Djenkins.install.runSetupWizard=false
