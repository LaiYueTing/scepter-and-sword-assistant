# 載入畫面的進度條與動畫，由杖劍傳說助手.spec 併進 PyInstaller 的啟動畫面腳本。
#
# 跑在 bootloader 的 Tcl 執行緒上，解壓階段也會動。進度訊息格式是「百分比|文字」（core/splash.py），
# bootloader 寫入的解壓檔名不符合格式，會被略過。

font create splashLabel -family {Microsoft JhengHei UI} -size 10
font create splashSmall -family {Microsoft JhengHei UI} -size 9

set bar_x0 28
set bar_x1 612
set bar_y 334

.root.canvas create line $bar_x0 $bar_y $bar_x1 $bar_y \
    -width 4 -capstyle round -fill #3A4352 -tags track
.root.canvas create line $bar_x0 $bar_y $bar_x0 $bar_y \
    -width 4 -capstyle round -fill #4CC2FF -tags fill
.root.canvas create line $bar_x0 $bar_y $bar_x0 $bar_y \
    -width 4 -capstyle round -fill #BDE9FF -tags sheen
.root.canvas create text $bar_x0 [expr {$bar_y - 11}] \
    -anchor sw -fill #E6EBF2 -font splashLabel -text "正在解壓程式檔案" -tags label
.root.canvas create text $bar_x1 [expr {$bar_y - 11}] \
    -anchor se -fill #A9B8CC -font splashSmall -text "0%" -tags pct
.root.canvas create text $bar_x1 292 \
    -anchor se -fill #C4CFDD -font splashSmall -text "v@VERSION@" -tags version

set splash_target 0
set splash_shown 0.0
set splash_since [clock milliseconds]
set splash_start $splash_since

proc on_status {args} {
    global status_text splash_target splash_since
    if {[regexp {^([0-9]*)\|(.*)$} $status_text -> pct text]} {
        if {$pct ne ""} {
            set splash_target $pct
            set splash_since [clock milliseconds]
        }
        .root.canvas itemconfigure label -text $text
    }
}
trace add variable status_text write on_status

# 回報點之間依時間往前爬，有上限，不會超過下一個回報點太多。
proc splash_tick {} {
    global splash_target splash_shown splash_since splash_start bar_x0 bar_x1 bar_y
    set now [clock milliseconds]
    set idle [expr {($now - $splash_since) / 1000.0}]
    if {$splash_target == 0} {
        set goal [expr {30.0 * (1.0 - exp(-$idle / 2.2))}]
    } else {
        set goal [expr {$splash_target + 14.0 * (1.0 - exp(-$idle / 1.5))}]
        if {$goal > 100} { set goal 100.0 }
    }
    if {$goal > $splash_shown} {
        set splash_shown [expr {$splash_shown + ($goal - $splash_shown) * 0.14}]
    }
    set width [expr {$bar_x1 - $bar_x0}]
    set x [expr {$bar_x0 + $width * $splash_shown / 100.0}]
    .root.canvas coords fill $bar_x0 $bar_y $x $bar_y

    # 進度條上往右掃過的亮光
    set span [expr {$x - $bar_x0 + 60.0}]
    set head [expr {$bar_x0 + fmod(($now - $splash_start) * 0.22, $span)}]
    set tail [expr {$head - 60.0}]
    if {$head > $x} { set head $x }
    if {$tail < $bar_x0} { set tail $bar_x0 }
    if {$tail >= $head} { set tail $head }
    .root.canvas coords sheen $tail $bar_y $head $bar_y

    .root.canvas itemconfigure pct -text "[expr {round($splash_shown)}]%"
    after 33 splash_tick
}

proc splash_fade {alpha} {
    wm attributes . -alpha $alpha
    if {$alpha < 1.0} {
        after 16 [list splash_fade [expr {min(1.0, $alpha + 0.09)}]]
    }
}

wm attributes . -alpha 0.0
after 10 [list splash_fade 0.09]
after 33 splash_tick

# 保險：Python 沒有關閉時自行結束。
after 45000 exit
