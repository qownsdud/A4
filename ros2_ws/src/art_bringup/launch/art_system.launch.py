"""키오스크·선화·경로추출·JobManager(+SQLite)·DrawingController 통합 실행 구성."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import EqualsSubstitution, LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    controller_mode = LaunchConfiguration('controller_mode')
    return LaunchDescription([
        DeclareLaunchArgument(
            'controller_mode',
            default_value='ros',
            description='실행기 선택: ros(일시정지·재개·외력감지 지원) 또는 standalone(draw_image_standalone.py 연동)',
        ),
        DeclareLaunchArgument(
            'virtual',
            default_value='false',
            description='standalone 모드에서 --virtual 전달 여부',
        ),
        DeclareLaunchArgument(
            'dry_run',
            default_value='false',
            description='standalone 모드에서 --dry-run 전달 여부',
        ),
        DeclareLaunchArgument(
            'skip_cal',
            default_value='false',
            description='standalone 모드에서 --skip-cal 전달 여부',
        ),
        Node(package='art_artwork_pipeline', executable='artwork_pipeline', output='screen'),
        Node(package='art_job_manager', executable='job_manager', output='screen'),
        Node(
            package='art_drawing_controller',
            executable='standalone_controller',
            output='screen',
            condition=IfCondition(EqualsSubstitution(controller_mode, 'standalone')),
            parameters=[{
                'virtual': LaunchConfiguration('virtual'),
                'dry_run': LaunchConfiguration('dry_run'),
                'skip_cal': LaunchConfiguration('skip_cal'),
            }],
        ),
        Node(
            package='art_drawing_controller',
            executable='drawing_controller',
            output='screen',
            condition=IfCondition(EqualsSubstitution(controller_mode, 'ros')),
        ),
        Node(package='art_kiosk_bridge', executable='bridge', output='screen'),
        Node(package='art_kiosk', executable='kiosk', output='screen'),
    ])
