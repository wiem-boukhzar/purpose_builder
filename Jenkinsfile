// See https://www.opendevstack.org/ods-documentation/ for usage and customization.

@Library('ods-jenkins-shared-library@4.x') _

odsComponentPipeline(
  imageStreamTag: 'ods/jenkins-agent-python:4.x',
  branchToEnvironmentMapping: [
    'master': 'dev',
    'nicolo_dev': 'dev',
    // 'release/': 'test'
  ]
) { context ->
  odsComponentFindOpenShiftImageOrElse(context) {
    createTestVirtualenv(context)
    stageUnitTest(context)
    stageBuild(context)
    odsComponentStageBuildOpenShiftImage(
      context,
      [
        resourceName: "${context.componentId}",
        dockerDir: "docker",
        buildArgs: [
          nexusHostWithBasicAuth: context.nexusHostWithBasicAuth,
          nexusHostWithoutScheme: context.nexusHostWithoutScheme,
        ],
      ],
    )
  }
  odsComponentStageRolloutOpenShiftDeployment(context)
}

def createTestVirtualenv(def context) {
  stage('Create virtualenv for tests') {
    sh(
      script: """
        python3.12 -m venv testvenv
        . ./testvenv/bin/activate
        pip install --upgrade pip
        pip install -r requirements-dev.txt
      """
    )
  }
}

def stageUnitTest(def context) {
  stage('Unit Test') {
    sh(
      script: """
        . ./testvenv/bin/activate
        export PYTHONPATH=${WORKSPACE}/src:\$PYTHONPATH
        if [ -d "tests" ]; then
          python -m pytest tests/ --junitxml=tests.xml -o junit_family=xunit2 --cov-report term-missing --cov-report xml --cov=backend
        else
          echo "No tests directory found, skipping pytest."
        fi
        if [ -f coverage.xml ]; then
          mkdir -p build/test-results/coverage/
          mv coverage.xml build/test-results/coverage/
        fi
        if [ -f tests.xml ]; then
          mkdir -p build/test-results/test/
          mv tests.xml build/test-results/test/
        fi
      """,
      label: "Running unit tests",
    )
  }
}

def stageBuild(def context) {
  stage('Build') {
    sh """
      rm -rf docker/src docker/data docker/requirements.txt
      cp -rv src docker/src
      cp -rv data docker/data
      cp -v requirements.txt docker/requirements.txt
    """
  }
}
