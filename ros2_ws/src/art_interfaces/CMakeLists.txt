# ROS 2 사용자 정의 Service/Message/Action의 Python/C++ 타입을 생성하는 빌드 설정
# .srv/.msg/.action 필드를 바꾸면 Bridge·Manager·Controller를 모두 재빌드해야 합니다.
cmake_minimum_required(VERSION 3.8)
project(art_interfaces)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
# TEAM_SYNC(JobManager/Robot): Freeze these fields before integrating real nodes.
rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/CreateJob.srv"
  "srv/ControlJob.srv"
  "srv/ControlDrawing.srv"
  "msg/JobStatus.msg"
  "action/ExecuteDrawing.action"
  "action/PrepareArtwork.action"
)
ament_export_dependencies(rosidl_default_runtime)
ament_package()
