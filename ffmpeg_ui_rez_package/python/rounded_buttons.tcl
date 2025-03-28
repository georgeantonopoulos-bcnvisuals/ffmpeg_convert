proc set_button_style {} {
    ttk::style configure TButton -padding {5 2} -relief flat
    
    ttk::style layout TButton {
        Button.button -children {
            Button.padding -children {
                Button.label -side left -expand true
            }
        }
    }
    
    ttk::style element create Button.button image \
        [list $::img::button_normal \
            {pressed !disabled} $::img::button_pressed \
            {active !disabled}  $::img::button_active \
            disabled $::img::button_disabled \
        ] -border 4 -sticky nsew
}

namespace eval img {
    variable button_normal [image create photo -data {
        iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAACXBIWXMAAA7DAAAOwwHHb6hkAAAA
        GXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAAKNJREFUOI3t1LEKwjAQBuAvahVE
        cHDxBQSfo4/g6FsUHN3ExcnFxaGLiKubi4h9AkEEsUMlpEnTpqCDPyQcucvdJRwhRBAETtoqz7J1
        +tBEfUvz3D4/MMMdT6P5QoMrnk7zC3qXhvvfwAIVKsP5FzDHAWejr8AKO5yMvgBbnFBafQZ2OOOS
        6Htgi7OjH8EKF9z+BRocE30PnPBA4ehHsME9xBuVtCKhv0KcIgAAAABJRU5ErkJggg==
    }]
    
    variable button_pressed [image create photo -data {
        iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAACXBIWXMAAA7DAAAOwwHHb6hkAAAA
        GXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAAJ1JREFUOI3t07EKwjAQBuAvahVE
        cHDxBQSfo4/g6FsUHN3ExcnFxaGLiKubi4h9AkEEsUMlpEnTXEHBHxKO3OXukiOECAKDZ23lWbZK
        H5qob2me2+cHpnjgZTSfqHHD22h+Qu/ScP8bmKPAzXD+BcxwxMXoK7DGHmejL8AOZ5RWn4E9Lrgm
        +h7Y4eLoR7DCFfd/gTWuib4HTrhHMfQj2OAR4g1otCIhyuqm5QAAAABJRU5ErkJggg==
    }]
    
    variable button_active [image create photo -data {
        iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAACXBIWXMAAA7DAAAOwwHHb6hkAAAA
        GXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAAKFJREFUOI3t07EKwjAQBuAvahVE
        cHDxBQSfo4/g6FsUHN3ExcnFxaGLiKubi4h9AkEEsUMlpEnTpqCDPyQcucvdJRwhRBAYa6s8y1bp
        QxP1Lc1z+/zAFHc8jeYLDa54Os0v6F0a7n8Dc1S4Gc6/gBkOOBt9BVbY4WT0BdjihNLqM7DDGZdE
        3wNbnB39CFa44PYv0OCa6HvggAeKoR/BBvcQb2TBIqFb1R+hAAAAAElFTkSuQmCC
    }]
    
    variable button_disabled [image create photo -data {
        iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAACXBIWXMAAA7DAAAOwwHHb6hkAAAA
        GXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAAKNJREFUOI3t1LEKwjAQBuAvahVE
        cHDxBQSfo4/g6FsUHN3ExcnFxaGLiKubi4h9AkEEsUMlpEnTpqCDPyQcucvdJRwhRBAETtoqz7J1
        +tBEfUvz3D4/MMMdT6P5QoMrnk7zC3qXhvvfwAIVKsP5FzDHAWejr8AKO5yMvgBbnFBafQZ2OOOS
        6Htgi7OjH8EKF9z+BRocE30PnPBA4ehHsME9xBuVtCKhv0KcIgAAAABJRU5ErkJggg==
    }]
}

set_button_style