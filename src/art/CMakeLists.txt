cmake_minimum_required(VERSION 3.8)
project(art)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/CreateJob.srv"
  "srv/ControlJob.srv"
  "msg/JobStatus.msg"
  "action/ExecuteDrawing.action"
  "action/PrepareArtwork.action"
)

ament_export_dependencies(rosidl_default_runtime)

# Python 서브패키지 설치 (rosidl이 생성하는 art/__init__.py와 충돌하지 않도록 서브폴더만 설치)
install(DIRECTORY
  art/artwork_pipeline
  art/drawing_controller
  art/job_manager
  art/kiosk
  art/kiosk_bridge
  DESTINATION "${PYTHON_INSTALL_DIR}/${PROJECT_NAME}"
)

install(PROGRAMS
  scripts/artwork_pipeline
  scripts/lineart
  scripts/plan_paths
  scripts/drawing_controller
  scripts/job_manager
  scripts/job_manager_test
  scripts/bridge
  scripts/kiosk
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
