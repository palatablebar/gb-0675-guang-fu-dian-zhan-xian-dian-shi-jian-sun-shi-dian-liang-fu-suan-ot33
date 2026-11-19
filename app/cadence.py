from app.errors import BusinessError

def cadence_of(context, device_id):
    """设备采样间隔(秒): 设备级 cadence_seconds 优先, 缺省回落全局 cadence_seconds。
    旧批次上下文无设备级键, 回落后与旧版全局600秒行为逐位一致。"""
    device = context['devices'].get(device_id, {})
    value = device.get('cadence_seconds', context.get('cadence_seconds', 600))
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise BusinessError('BAD_CADENCE', '采样间隔须为正整数秒')
    try:
        cadence = int(value)
    except (TypeError, ValueError):
        raise BusinessError('BAD_CADENCE', '采样间隔须为正整数秒')
    if not 60 <= cadence <= 3600:
        raise BusinessError('BAD_CADENCE', '采样间隔须在60~3600秒之间')
    return cadence
