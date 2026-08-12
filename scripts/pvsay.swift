// pvsay - speak text with the user's macOS Personal Voice.
//
// Usage:
//   pvsay --check           Exit 0 if a Personal Voice is usable, else 1.
//   pvsay [-r rate] <text>  Speak the text. Rate is words per minute.
//
// Personal Voice needs permission per app. The first run shows a system
// dialog for the terminal. It also needs "Allow apps to request to use"
// turned on in System Settings, Accessibility, Personal Voice.

import AVFoundation
import Foundation

let args = Array(CommandLine.arguments.dropFirst())

func authorize() -> Bool {
    // The callback arrives on the main queue, so pump the run loop
    // instead of blocking the main thread.
    var ok = false
    var done = false
    AVSpeechSynthesizer.requestPersonalVoiceAuthorization { status in
        ok = (status == .authorized)
        done = true
    }
    let deadline = Date().addingTimeInterval(120)
    while !done && Date() < deadline {
        RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
    }
    return ok
}

func personalVoice() -> AVSpeechSynthesisVoice? {
    AVSpeechSynthesisVoice.speechVoices().first { v in
        v.voiceTraits.contains(.isPersonalVoice)
    }
}

guard authorize() else {
    FileHandle.standardError.write(Data("pvsay: Personal Voice permission is not granted.\n".utf8))
    exit(2)
}
guard let voice = personalVoice() else {
    FileHandle.standardError.write(Data("pvsay: no Personal Voice is available.\n".utf8))
    exit(1)
}

if args.first == "--check" {
    print("Personal Voice ready: \(voice.name)")
    exit(0)
}

var rate = AVSpeechUtteranceDefaultSpeechRate
var text = ""
var i = 0
while i < args.count {
    if args[i] == "-r", i + 1 < args.count, let wpm = Double(args[i + 1]) {
        // Map words per minute onto the AVSpeech 0...1 range.
        // The default rate 0.5 is close to 180 words per minute.
        rate = Float(min(0.9, max(0.1, 0.5 * (wpm / 180.0))))
        i += 2
    } else {
        text = args[i...].joined(separator: " ")
        break
    }
}
if text.isEmpty { exit(0) }

final class Waiter: NSObject, AVSpeechSynthesizerDelegate {
    let sem = DispatchSemaphore(value: 0)
    func speechSynthesizer(_ s: AVSpeechSynthesizer,
                           didFinish utterance: AVSpeechUtterance) { sem.signal() }
    func speechSynthesizer(_ s: AVSpeechSynthesizer,
                           didCancel utterance: AVSpeechUtterance) { sem.signal() }
}

let synth = AVSpeechSynthesizer()
let waiter = Waiter()
synth.delegate = waiter
let utterance = AVSpeechUtterance(string: text)
utterance.voice = voice
utterance.rate = rate
synth.speak(utterance)

// Keep the run loop alive while the speech plays.
while waiter.sem.wait(timeout: .now()) != .success {
    RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
}
