package require Tk 8.6

namespace eval ttk::theme::dark {
    variable colors
    array set colors {
        -fg             "#ffffff"
        -bg             "#2b2b2b"
        -disabledfg     "#999999"
        -selectfg       "#ffffff"
        -selectbg       "#4a6984"
    }

    proc LoadImages {imgdir} {
        variable I
        foreach file [glob -directory $imgdir *.png] {
            set img [file tail [file rootname $file]]
            set I($img) [image create photo -file $file -format png]
        }
    }

    LoadImages [file join [file dirname [info script]] dark]

    ttk::style theme create dark -parent default -settings {
        ttk::style configure "." \
            -background $colors(-bg) \
            -foreground $colors(-fg) \
            -troughcolor $colors(-bg) \
            -focuscolor $colors(-selectbg) \
            -selectbackground $colors(-selectbg) \
            -selectforeground $colors(-selectfg) \
            -insertcolor $colors(-fg) \
            -insertwidth 1 \
            -fieldbackground $colors(-selectbg) \
            -font {"Roboto" 10} \
            -borderwidth 1 \
            -relief flat

        ttk::style map "." \
            -background [list disabled $colors(-bg) active $colors(-selectbg)] \
            -foreground [list disabled $colors(-disabledfg)] \
            -selectbackground [list !focus $colors(-selectbg)] \
            -selectforeground [list !focus $colors(-selectfg)]

        # Button
        ttk::style configure TButton \
            -padding {5 2} \
            -anchor center \
            -foreground $colors(-fg)
        
        ttk::style map TButton \
            -foreground [list pressed $colors(-selectfg) active $colors(-selectfg)] \
            -background [list pressed $colors(-selectbg) active $colors(-selectbg)]

        ttk::style layout TButton {
            Button.button -children {
                Button.padding -children {
                    Button.label -side left -expand true
                }
            }
        }

        ttk::style element create Button.button image \
            [list $I(button-normal) \
                {pressed !disabled} $I(button-pressed) \
                {active !disabled}  $I(button-active) \
                disabled $I(button-disabled) \
            ] -border 4 -sticky nsew

        # Entry
        ttk::style configure TEntry \
            -foreground $colors(-fg) \
            -background $colors(-bg) \
            -fieldbackground $colors(-bg) \
            -insertcolor $colors(-fg)

        # Combobox
        ttk::style configure TCombobox \
            -foreground $colors(-fg) \
            -background $colors(-bg) \
            -fieldbackground $colors(-bg) \
            -arrowcolor $colors(-fg)

        ttk::style map TCombobox \
            -fieldbackground [list \
                readonly $colors(-bg) \
                active $colors(-selectbg) \
                focus $colors(-selectbg) \
            ] \
            -selectbackground [list \
                readonly $colors(-selectbg) \
                !focus $colors(-selectbg) \
            ] \
            -selectforeground [list \
                readonly $colors(-selectfg) \
                !focus $colors(-selectfg) \
            ]

        # Progressbar
        ttk::style configure TProgressbar \
            -background $colors(-selectbg) \
            -troughcolor $colors(-bg)
    }
}

# Load the images for the buttons
namespace eval img {
    variable button_normal [image create photo -data {
        iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAACXBIWXMAAA7DAAAOwwHHb6hkAAAAGXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAAKNJREFUOI3t1LEKwjAQBuAvahVEcHDxBQSfo4/g6FsUHN3ExcnFxaGLiKubi4h9AkEEsUMlpEnTpqCDPyQcucvdJRwhRBAETtoqz7J1+tBEfUvz3D4/MMMdT6P5QoMrnk7zC3qXhvvfwAIVKsP5FzDHAWejr8AKO5yMvgBbnFBafQZ2OOOS6Htgi7OjH8EKF9z+BRocE30PnPBA4ehHsME9xBuVtCKhv0KcIgAAAABJRU5ErkJggg==
    }]
    
    variable button_pressed [image create photo -data {
        iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAACXBIWXMAAA7DAAAOwwHHb6hkAAAAGXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAAJ1JREFUOI3t07EKwjAQBuAvahVEcHDxBQSfo4/g6FsUHN3ExcnFxaGLiKubi4h9AkEEsUMlpEnTXEHBHxKO3OXukiOECAKDZ23lWbZKH5qob2me2+cHpnjgZTSfqHHD22h+Qu/ScP8bmKPAzXD+BcxwxMXoK7DGHmejL8AOZ5RWn4E9Lrgm+h7Y4eLoR7DCFfd/gTWuib4HTrhHMfQj2OAR4g1otCIhyuqm5QAAAABJRU5ErkJggg==
    }]
    
    variable button_active [image create photo -data {
        iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAACXBIWXMAAA7DAAAOwwHHb6hkAAAAGXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAAKFJREFUOI3t07EKwjAQBuAvahVEcHDxBQSfo4/g6FsUHN3ExcnFxaGLiKubi4h9AkEEsUMlpEnTpqCDPyQcucvdJRwhRBAYa6s8y1bpQxP1Lc1z+/zAFHc8jeYLDa54Os0v6F0a7n8Dc1S4Gc6/gBkOOBt9BVbY4WT0BdjihNLqM7DDGZdE3wNbnB39CFa44PYv0OCa6HvggAeKoR/BBvcQb2TBIqFb1R+hAAAAAElFTkSuQmCC
    }]
    
    variable button_disabled [image create photo -data {
        iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAACXBIWXMAAA7DAAAOwwHHb6hkAAAAGXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAAKNJREFUOI3t1LEKwjAQBuAvahVEcHDxBQSfo4/g6FsUHN3ExcnFxaGLiKubi4h9AkEEsUMlpEnTpqCDPyQcucvdJRwhRBAETtoqz7J1+tBEfUvz3D4/MMMdT6P5QoMrnk7zC3qXhvvfwAIVKsP5FzDHAWejr8AKO5yMvgBbnFBafQZ2OOOS6Htgi7OjH8EKF9z+BRocE30PnPBA4ehHsME9xBuVtCKhv0KcIgAAAABJRU5ErkJggg==
    }]
}

# Set the dark theme
ttk::style theme use dark
