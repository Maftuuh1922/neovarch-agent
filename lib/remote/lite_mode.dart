// "Mode ringan": the setting itself lives in AppearanceController
// (`nv.perf.lite`); this decides when to suggest it — once, on phones with
// little RAM (Android `ActivityManager.isLowRamDevice` or < 4.5 GB total).
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../data/device_tools.dart' show deviceCall;

const kLiteSuggested = 'nv.perf.liteSuggested';

/// Below this total RAM the suggestion shows (a "4 GB" phone reports
/// about 3.6–3.8 GB; "6 GB" about 5.5 GB).
const liteRamThreshold = 4608 * 1024 * 1024; // 4.5 GiB

typedef MemoryInfoReader = Future<Map?> Function();

/// `{total, low_ram, mem_class}` from MainActivity, or null off Android.
Future<Map?> readMemoryInfo() async {
  if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return null;
  try {
    return await deviceCall<Map>('memoryInfo');
  } catch (_) {
    return null;
  }
}

/// Swappable in tests.
MemoryInfoReader liteMemoryReader = readMemoryInfo;

bool isLowRam(Map? info) {
  if (info == null) return false;
  if (info['low_ram'] == true) return true;
  final t = info['total'];
  return t is num && t > 0 && t < liteRamThreshold;
}

/// "3,7 GB" (Indonesian decimal comma), or null when unknown.
String? ramLabel(Map? info) {
  final t = info?['total'];
  if (t is! num || t <= 0) return null;
  return '${(t / (1024 * 1024 * 1024)).toStringAsFixed(1).replaceAll('.', ',')} GB';
}

/// The memory info when the suggestion should show now (and records that it
/// did, so it shows once per install); null otherwise.
Future<Map?> liteSuggestion(SharedPreferences prefs, {required bool liteOn, MemoryInfoReader? read}) async {
  if (liteOn || prefs.getBool(kLiteSuggested) == true) return null;
  final info = await (read ?? liteMemoryReader)();
  if (!isLowRam(info)) return null;
  await prefs.setBool(kLiteSuggested, true);
  return info;
}
