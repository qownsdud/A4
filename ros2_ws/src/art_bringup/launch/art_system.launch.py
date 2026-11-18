"""키오스크·선화·벡터화·경로추출 및 draw_image_standalone.py 연동을 실행합니다."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'virtual',
            default_value='false',
            description='draw_image_standalone.py 가상 모드(--virtual) 사용 여부',
        ),
        DeclareLaunchArgument(
            'dry_run',
            default_value='false',
            description='로봇 이동 없이 변환/배치 결과만 확인(--dry-run)',
        ),
        DeclareLaunchArgument(
            'skip_cal',
            default_value='false',
            description='9점 자동 캘리브레이션 건너뛰기(--skip-cal)',
        ),
        Node(package='art_artwork_pipeline', executable='artwork_pipeline', output='screen'),
        Node(
            package='art_artwork_pipeline',
            executable='standalone_drawer',
            output='screen',
            parameters=[{
                'virtual': LaunchConfiguration('virtual'),
                'dry_run': LaunchConfiguration('dry_run'),
                'skip_cal': LaunchConfiguration('skip_cal'),
            }],
        ),
        Node(package='art_kiosk_bridge', executable='bridge', output='screen'),
        Node(package='art_kiosk', executable='kiosk', output='screen'),
    ])
